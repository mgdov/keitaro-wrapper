from copy import deepcopy
from datetime import datetime, timezone
from threading import Lock
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.exc import StaleDataError

from app.config import Settings
from app.keitaro import KeitaroClient
from app.models import Campaign, Stream
from app.weights import RuleError, merge_remote, payload, redistribute, signature


class CreateCampaign(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    country: str = Field(pattern=r'^[A-Za-z]{2}$')
    offer_id: int = Field(gt=0)
    domain_id: int = Field(default=1813, gt=0)
    group_id: int = Field(default=10332, gt=0)
    traffic_source_id: int = Field(default=836, gt=0)

    @field_validator('name')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Название не должно быть пустым')
        return value.strip()

    @field_validator('country')
    @classmethod
    def country_code(cls, value):
        codes = set(('AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW').split())
        if value.upper() not in codes:
            raise ValueError('Неизвестный код страны ISO 3166-1 alpha-2')
        return value.upper()


class Edit(BaseModel):
    version: int = Field(ge=1)
    action: Literal['add', 'remove', 'restore', 'pin', 'unpin']
    offer_id: int = Field(gt=0)
    share: int | None = Field(default=None, ge=0, le=100)


class Version(BaseModel):
    version: int = Field(ge=1)


def create_app(settings: Settings | None = None, remote=None):
    settings = settings or Settings()
    engine = create_engine(settings.database_url,
                           connect_args={'check_same_thread': False, 'timeout': 30}
                           if settings.database_url.startswith('sqlite') else {})
    if settings.database_url.startswith('sqlite'):
        @event.listens_for(engine, 'connect')
        def sqlite_setup(connection, _):
            connection.execute('PRAGMA foreign_keys=ON')
    sessions = sessionmaker(engine, expire_on_commit=False)
    client = remote or KeitaroClient(settings)
    app = FastAPI(title='Keitaro Wrapper', version='0.1.0')
    app.state.engine = engine
    app.state.sessions = sessions
    app.state.settings = settings
    # Single backend worker: serializes local edits with Fetch and remote Push.
    lock = Lock()

    def db():
        with lock, sessions() as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    @app.middleware('http')
    async def local_writes_only(request: Request, call_next):
        # Browser requests go through Next's same-origin proxy. Block cross-site forms/fetch.
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            if request.headers.get('sec-fetch-site') == 'cross-site':
                return JSONResponse(status_code=403, content={'detail': 'Cross-site запрос отклонён.'})
        return await call_next(request)

    @app.exception_handler(RuleError)
    async def rules_error(_, error):
        return JSONResponse(status_code=422, content={'detail': str(error)})

    @app.exception_handler(StaleDataError)
    async def stale_error(_, error):
        return JSONResponse(status_code=409, content={'detail': 'Данные изменились. Обновите страницу.'})

    def require_campaign(session, cid):
        campaign = session.get(Campaign, cid)
        if not campaign:
            raise HTTPException(404, 'Сначала загрузите кампанию из Keitaro.')
        return campaign

    def require_stream(session, sid, version):
        stream = session.get(Stream, sid)
        if not stream:
            raise HTTPException(404, 'Поток не найден.')
        if stream.version != version:
            raise HTTPException(409, 'Устаревшая версия. Обновите данные.')
        return stream

    def render_stream(stream):
        return dict(id=stream.id, name=stream.name, position=stream.position,
                    editable=stream.editable, version=stream.version,
                    dirty=stream.draft != stream.baseline, offers=stream.draft,
                    published=stream.baseline, updated_at=stream.updated_at)

    def render(campaign):
        return dict(id=campaign.id, name=campaign.name,
                    admin_url=settings.keitaro_base_url.split('/admin_api/')[0] + f'/admin/#!/campaign.editor/{campaign.id}',
                    streams=[render_stream(stream) for stream in campaign.streams])

    def save_snapshot(stream, rows):
        stream.draft = deepcopy(rows)
        stream.baseline = deepcopy(rows)
        stream.updated_at = datetime.now(timezone.utc).isoformat()

    def fetch_campaign(session, cid):
        local = session.get(Campaign, cid)
        if local and any(s.draft != s.baseline for s in local.streams):
            raise HTTPException(409, 'Сначала опубликуйте или отмените черновики всех потоков.')
        campaign_data = client.get(f'/campaigns/{cid}')
        streams_data = client.get(f'/campaigns/{cid}/streams')
        names = {o['id']: o['name'] for o in client.get('/offers')}
        if local is None:
            local = Campaign(id=cid, name=campaign_data['name'])
            session.add(local)
        local.name = campaign_data['name']
        current = {s.id: s for s in local.streams}
        seen = set()
        for item in streams_data:
            sid = int(item['id'])
            seen.add(sid)
            stream = current.get(sid)
            if stream is None:
                stream = Stream(id=sid, name=item['name'], baseline=[], draft=[])
                local.streams.append(stream)
            stream.name = item['name']
            stream.position = int(item.get('position', 0))
            rows = merge_remote(stream.baseline, item.get('offers') or [], names)
            stream.editable = bool(rows)
            save_snapshot(stream, rows)
        for sid, stream in current.items():
            if sid not in seen:
                local.streams.remove(stream)
        session.flush()
        return local

    @app.get('/api/health')
    def health():
        return {'status': 'ok', 'configured': bool(settings.keitaro_api_key.get_secret_value()),
                'campaign_prefix': settings.campaign_prefix}

    @app.get('/api/catalog')
    def catalog():
        return dict(domains=client.get('/domains'), groups=client.get('/groups?type=campaigns'),
                    sources=client.get('/traffic_sources'), offers=client.get('/offers'))

    @app.get('/api/offers')
    def offers(q: str = Query(default='', max_length=200)):
        needle = q.casefold().strip()
        return [o for o in client.get('/offers') if o.get('state', 'active') == 'active'
                and (needle in o['name'].casefold() or needle in str(o['id']))][:30]

    @app.get('/api/campaigns')
    def campaigns():
        # Explicitly page: real Keitaro may not return the whole collection at once.
        rows = []
        for offset in range(0, 10000, 100):
            page = client.get(f'/campaigns?offset={offset}&limit=100')
            rows.extend({key: campaign[key] for key in ('id', 'name', 'state', 'group_id', 'traffic_source_id')
                         if key in campaign} for campaign in page)
            if len(page) < 100:
                return rows
        raise HTTPException(502, 'Слишком много кампаний. Ограничьте выборку на стороне Keitaro.')

    @app.post('/api/campaigns', status_code=201)
    def create(body: CreateCampaign, session: Session = Depends(db)):
        offer = client.get(f'/offers/{body.offer_id}')
        if offer.get('state', 'active') != 'active':
            raise RuleError('Выберите активный оффер.')
        for path, value in [('/domains', body.domain_id), ('/groups?type=campaigns', body.group_id),
                            ('/traffic_sources', body.traffic_source_id)]:
            if not any(row['id'] == value for row in client.get(path)):
                raise RuleError('Выбранный домен, группа или источник отсутствует в Keitaro.')
        name = body.name if body.name.startswith(settings.campaign_prefix) else settings.campaign_prefix + body.name
        cid = None
        try:
            created = client.request('POST', '/campaigns', dict(name=name, type='position',
                domain_id=body.domain_id, group_id=body.group_id, traffic_source_id=body.traffic_source_id))
            cid = int(created['id'])
            client.request('POST', '/streams', dict(campaign_id=cid, name='Geo → Google', position=1,
                type='regular', schema='redirect', action_type='http', action_payload='https://google.com',
                filters=[dict(name='country', mode='accept', payload=[body.country.upper()])]))
            client.request('POST', '/streams', dict(campaign_id=cid, name='Офферы', position=2,
                type='default', schema='landings', offers=[dict(offer_id=body.offer_id, share=100, state='active')]))
        except HTTPException as error:
            # Do not blindly repeat POST or delete a partially created campaign.
            detail = error.detail
            if cid is not None:
                detail += f' Кампания #{cid} создана частично; проверьте её в админке перед повтором.'
            raise HTTPException(502, detail) from None
        try:
            return render(fetch_campaign(session, cid))
        except HTTPException as error:
            raise HTTPException(502, f'Кампания #{cid} создана. Не создавайте повторно: загрузите её по ID. {error.detail}') from None

    @app.get('/api/campaigns/{cid}')
    def local_campaign(cid: int, session: Session = Depends(db)):
        return render(require_campaign(session, cid))

    @app.post('/api/campaigns/{cid}/fetch')
    def fetch(cid: int, session: Session = Depends(db)):
        return render(fetch_campaign(session, cid))

    @app.patch('/api/streams/{sid}')
    def edit(sid: int, body: Edit, session: Session = Depends(db)):
        stream = require_stream(session, sid, body.version)
        if not stream.editable:
            raise RuleError('Поток без офферов нельзя менять этим редактором.')
        rows = deepcopy(stream.draft)
        row = next((r for r in rows if r['offer_id'] == body.offer_id), None)
        if body.action == 'add':
            if row:
                raise RuleError('Оффер уже есть в потоке. Для архивного используйте «Вернуть».')
            offer = client.get(f'/offers/{body.offer_id}')
            if offer.get('state', 'active') != 'active':
                raise RuleError('Оффер недоступен.')
            rows.append(dict(offer_id=body.offer_id, name=offer['name'], share=0, removed=False, pinned_share=None))
        else:
            if row is None:
                raise HTTPException(404, 'Оффер не найден в потоке.')
            if body.action == 'remove':
                row['removed'] = True
            elif body.action == 'restore':
                offer = client.get(f'/offers/{body.offer_id}')
                if offer.get('state', 'active') != 'active':
                    raise RuleError('Оффер недоступен в каталоге Keitaro.')
                row['removed'] = False
            elif body.action == 'pin':
                if row['removed']:
                    raise RuleError('Архивному офферу нельзя закрепить долю.')
                row['pinned_share'] = row['share'] if body.share is None else body.share
            elif body.action == 'unpin':
                row['pinned_share'] = None
        stream.draft = redistribute(rows)
        stream.updated_at = datetime.now(timezone.utc).isoformat()
        session.flush()
        return render_stream(stream)

    @app.post('/api/streams/{sid}/cancel')
    def cancel(sid: int, body: Version, session: Session = Depends(db)):
        stream = require_stream(session, sid, body.version)
        stream.draft = deepcopy(stream.baseline)
        session.flush()
        return render_stream(stream)

    @app.post('/api/streams/{sid}/push')
    def push(sid: int, body: Version, session: Session = Depends(db)):
        stream = require_stream(session, sid, body.version)
        if not stream.editable or stream.draft == stream.baseline:
            return render_stream(stream)
        checked = redistribute(stream.draft)
        intended = payload(checked)
        remote = client.get(f'/streams/{sid}')
        actual = signature(remote.get('offers') or [])
        # Also recover a lost acknowledgement: the intended state is already remote.
        if actual != signature(intended):
            if actual != signature(payload(stream.baseline)):
                raise HTTPException(409, 'Поток изменён в Keitaro. Сохраните черновик отдельно, отмените его и выполните Fetch.')
            client.request('PUT', f'/streams/{sid}', {'offers': intended})
            confirmed = client.get(f'/streams/{sid}')
            if signature(confirmed.get('offers') or []) != signature(intended):
                raise HTTPException(502, 'Keitaro не подтвердил опубликованный состав. Черновик сохранён.')
        save_snapshot(stream, checked)
        session.flush()
        return render_stream(stream)

    return app


app = create_app()
