'use client';

import { FormEvent, useCallback, useEffect, useRef, useState } from 'react';

type Item = {id: number; name: string; state?: string};
type Catalog = {offers: Item[]; domains: Item[]; groups: Item[]; sources: Item[]};
type Offer = {offer_id: number; name: string; share: number; removed: boolean; pinned_share: number | null};
type Stream = {id: number; name: string; position: number; editable: boolean; version: number; dirty: boolean; offers: Offer[]; published: Offer[]};
type Campaign = {id: number; name: string; admin_url: string; streams: Stream[]};
type Health = {configured: boolean; campaign_prefix: string};

async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(`/api${path}`, {method, headers: {'Content-Type':'application/json'}, body: body === undefined ? undefined : JSON.stringify(body)});
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data?.detail;
    throw new Error(typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map((d: {msg: string}) => d.msg).join('; ') : `Ошибка HTTP ${response.status}. Проверьте backend.`);
  }
  return data as T;
}

function OfferPicker({offers, excluded, value, onChange, id}: {offers: Item[]; excluded: number[]; value: string; onChange: (v: string) => void; id: string}) {
  return <><input id={id} list={`${id}-list`} value={value} onChange={e => onChange(e.target.value)} placeholder="ID или название оффера" autoComplete="off"/>
    <datalist id={`${id}-list`}>{offers.filter(o => o.state !== 'disabled' && o.state !== 'deleted' && !excluded.includes(o.id)).map(o => <option key={o.id} value={`${o.id} · ${o.name}`}/>)}</datalist></>;
}

function resolveOffer(value: string, offers: Item[]): number {
  const id = Number(value.split(' · ')[0].trim());
  if (!Number.isInteger(id) || !offers.some(o => o.id === id)) throw new Error('Выберите оффер из списка или введите его ID.');
  return id;
}

function StreamCard({stream, catalog, busy, onAction}: {stream: Stream; catalog: Catalog; busy: boolean; onAction: (sid: number, action: string, body?: object) => Promise<void>}) {
  const [chosen, setChosen] = useState('');
  const [shares, setShares] = useState<Record<number,string>>({});
  const [localError, setLocalError] = useState('');
  const active = stream.offers.filter(o => !o.removed);
  async function add(e: FormEvent) {
    e.preventDefault(); setLocalError('');
    try {const id = resolveOffer(chosen, catalog.offers); await onAction(stream.id, 'add', {offer_id:id}); setChosen('');}
    catch(error) {setLocalError((error as Error).message);}
  }
  return <section className={`stream ${stream.dirty ? 'dirty' : ''}`}>
    <header className="stream-head"><div><span className="eyebrow">ПОТОК {stream.position} · #{stream.id}</span><h3>{stream.name}</h3></div>
      <span className={`badge ${stream.dirty ? 'amber' : 'green'}`}>{stream.dirty ? 'Черновик' : 'Синхронизирован'}</span></header>
    {!stream.editable ? <p className="muted empty-flow">Поток без офферов. Его фильтры и перенаправление сохраняются без изменений.</p> : <>
      <div className="stream-summary"><span>{active.length} активных · {stream.offers.length - active.length} в архиве</span><strong>Сумма долей: {active.reduce((sum, o) => sum + o.share, 0)}%</strong></div>
      <div className="table-scroll"><table><thead><tr><th>Оффер</th><th>Доля</th><th>Закрепление</th><th>Действие</th></tr></thead><tbody>
        {stream.offers.map(offer => <tr key={offer.offer_id} className={offer.removed ? 'archived' : ''}>
          <td><span className="offer-id">#{offer.offer_id}</span><div className="offer-name">{offer.name}</div>{offer.removed && <span className="archive-label">В архиве</span>}</td>
          <td><strong className="share">{offer.share}%</strong></td>
          <td>{!offer.removed && <div className="pin-controls"><input type="number" min="0" max="100" aria-label={`Доля оффера ${offer.offer_id}`} value={shares[offer.offer_id] ?? String(offer.pinned_share ?? offer.share)} onChange={e => setShares({...shares, [offer.offer_id]: e.target.value})} disabled={busy}/>
            <button className={`small ${offer.pinned_share !== null ? 'pinned' : 'secondary'}`} disabled={busy} onClick={() => {
              setLocalError('');
              const share = Number(shares[offer.offer_id] ?? offer.share);
              if (offer.pinned_share === null && (!Number.isInteger(share) || share < 0 || share > 100)) {setLocalError('Доля должна быть целым числом от 0 до 100.'); return;}
              void onAction(stream.id, offer.pinned_share !== null ? 'unpin' : 'pin', {offer_id:offer.offer_id, share}).catch(() => {});
            }}>{offer.pinned_share !== null ? 'Освободить' : 'Закрепить'}</button></div>}</td>
          <td><button className="small secondary" disabled={busy} onClick={() => void onAction(stream.id, offer.removed ? 'restore' : 'remove', {offer_id:offer.offer_id}).catch(() => {})}>{offer.removed ? 'Вернуть' : 'Убрать'}</button></td>
        </tr>)}
      </tbody></table></div>
      <form className="add-offer" onSubmit={add}><label htmlFor={`offer-${stream.id}`} className="sr-only">Добавить оффер в поток {stream.id}</label><OfferPicker id={`offer-${stream.id}`} offers={catalog.offers} excluded={stream.offers.map(o => o.offer_id)} value={chosen} onChange={setChosen}/><button className="secondary" disabled={busy || !chosen}>Добавить оффер</button></form>
      {localError && <p role="alert" className="inline-error">{localError}</p>}
      {stream.dirty && <div className="publish-bar"><span>Изменения ещё не отправлены в Keitaro</span><div><button className="secondary" disabled={busy} onClick={() => void onAction(stream.id, 'cancel').catch(() => {})}>Отменить</button><button disabled={busy} onClick={() => void onAction(stream.id, 'push').catch(() => {})}>Опубликовать</button></div></div>}
    </>}
  </section>;
}

export default function Home() {
  const [health, setHealth] = useState<Health | null>(null);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [campaigns, setCampaigns] = useState<Item[]>([]);
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [tab, setTab] = useState<'editor'|'create'>('editor');
  const [selected, setSelected] = useState('');
  const [name, setName] = useState('');
  const [country, setCountry] = useState('AU');
  const [offer, setOffer] = useState('');
  const [domain, setDomain] = useState('');
  const [group, setGroup] = useState('');
  const [source, setSource] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const inFlight = useRef(false);

  const initialize = useCallback(async () => {
    setError('');
    try {
      const h = await api<Health>('/health'); setHealth(h);
      if (!h.configured) {setError('Добавьте KEITARO_API_KEY в окружение backend и перезапустите его.'); return;}
      const [c, list] = await Promise.all([api<Catalog>('/catalog'), api<Item[]>('/campaigns')]);
      setCatalog(c); setCampaigns(list);
      setDomain(String(c.domains[0]?.id ?? '')); setGroup(String(c.groups[0]?.id ?? '')); setSource(String(c.sources[0]?.id ?? ''));
    } catch(e) {setError((e as Error).message);}
  }, []);
  useEffect(() => {void initialize();}, [initialize]);
  const dirty = campaign?.streams.some(s => s.dirty) ?? false;
  useEffect(() => {
    function warn(e: BeforeUnloadEvent) {if (dirty) {e.preventDefault(); e.returnValue = '';}}
    window.addEventListener('beforeunload', warn); return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);

  async function perform(task: () => Promise<void>) {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true); setError(''); setNotice('');
    try {await task();} catch(e) {setError((e as Error).message); throw e;}
    finally {inFlight.current = false; setBusy(false);}
  }
  async function openCampaign(e: FormEvent) {
    e.preventDefault();
    if (dirty && campaign?.id !== Number(selected) && !window.confirm('Черновики сохранятся в локальной базе. Переключиться на другую кампанию?')) return;
    await perform(async () => {
      const id = Number(selected);
      try {setCampaign(await api<Campaign>(`/campaigns/${id}`));}
      catch(e) {
        // Only a local 404 should trigger Fetch; other errors remain visible.
        if ((e as Error).message !== 'Сначала загрузите кампанию из Keitaro.') throw e;
        setCampaign(await api<Campaign>(`/campaigns/${id}/fetch`, 'POST'));
      }
    }).catch(() => {});
  }
  async function create(e: FormEvent) {
    e.preventDefault();
    await perform(async () => {
      if (!catalog) return;
      const result = await api<Campaign>('/campaigns', 'POST', {name, country, offer_id:resolveOffer(offer, catalog.offers), domain_id:Number(domain), group_id:Number(group), traffic_source_id:Number(source)});
      setCampaign(result); setSelected(String(result.id)); setCampaigns(await api<Item[]>('/campaigns')); setTab('editor'); setName(''); setOffer(''); setNotice('Кампания и два потока созданы в Keitaro.');
    }).catch(() => {});
  }
  async function streamAction(sid: number, action: string, body = {}) {
    await perform(async () => {
      const current = campaign?.streams.find(s => s.id === sid);
      if (!current) return;
      const special = action === 'push' || action === 'cancel';
      const result = await api<Stream>(`/streams/${sid}${special ? `/${action}` : ''}`, special ? 'POST' : 'PATCH', {version:current.version, ...(special ? {} : {action}), ...body});
      setCampaign(prev => prev ? {...prev, streams:prev.streams.map(s => s.id === sid ? result : s)} : prev);
      if (action === 'push') setNotice('Изменения опубликованы и подтверждены Keitaro.');
      if (action === 'cancel') setNotice('Черновик отменён. Восстановлено последнее синхронизированное состояние.');
    });
  }
  return <div className="shell">
    <aside><a className="brand" href="/">k<span>·</span> wrapper</a><p className="aside-label">РАБОЧЕЕ ПРОСТРАНСТВО</p><button className={tab === 'editor' ? 'nav active' : 'nav'} onClick={() => setTab('editor')}>Кампании <span>↗</span></button><button className={tab === 'create' ? 'nav active' : 'nav'} onClick={() => setTab('create')}>Новая кампания <span>＋</span></button><div className="aside-bottom"><span className="status-dot"/> Keitaro Admin API<br/><small>Локальные черновики · явная публикация</small></div></aside>
    <main><div className="topline"><span>УПРАВЛЕНИЕ ТРАФИКОМ</span><span className="badge">Тестовый стенд</span></div>
      <header className="page-head"><div><h1>{tab === 'create' ? 'Новая кампания' : 'Кампании'}</h1><p className="muted">{tab === 'create' ? 'Название, гео и оффер — два потока создадутся автоматически.' : 'Управляйте офферами, сохраняйте черновики и публикуйте изменения.'}</p></div>{tab === 'editor' && <button onClick={() => setTab('create')}>＋ Создать кампанию</button>}</header>
      {error && <div role="alert" className="alert error"><strong>Не удалось выполнить операцию</strong><p>{error}</p>{!catalog && <button className="small secondary" onClick={() => void initialize()}>Повторить подключение</button>}</div>}
      {notice && <div role="status" className="alert success">{notice}</div>}
      {busy && <div role="status" className="busy">Выполняем запрос…</div>}
      {tab === 'create' ? <form className="create-card" onSubmit={create}><h2>Параметры кампании</h2><label htmlFor="campaign-name">Название</label><div className="prefix-input"><span>{health?.campaign_prefix ?? 'test_tadzhibov_'}</span><input id="campaign-name" required maxLength={180} value={name} onChange={e => setName(e.target.value)} placeholder="campaign1"/></div>
        <div className="two-columns"><div><label htmlFor="geo">Код страны</label><input id="geo" required pattern="[A-Za-z]{2}" maxLength={2} value={country} onChange={e => setCountry(e.target.value.toUpperCase())} placeholder="AU"/><small>Двухбуквенный код, например AU или MX</small></div><div><label htmlFor="new-offer">Оффер</label><OfferPicker id="new-offer" offers={catalog?.offers ?? []} excluded={[]} value={offer} onChange={setOffer}/></div></div>
        <div className="three-columns">{[['Домен', domain, setDomain, catalog?.domains], ['Группа', group, setGroup, catalog?.groups], ['Источник', source, setSource, catalog?.sources]].map(([label, value, setter, items], i) => <div key={i}><label htmlFor={`setting-${i}`}>{label as string}</label><select id={`setting-${i}`} required value={value as string} onChange={e => (setter as (s:string)=>void)(e.target.value)}>{(items as Item[] | undefined)?.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></div>)}</div>
        <div className="flow-preview"><div><b>01</b><span>Выбранная страна</span><strong>→ Google</strong></div><div><b>02</b><span>Остальной трафик</span><strong>→ Оффер · 100%</strong></div></div><button disabled={busy || !catalog}>Создать в Keitaro</button></form> : <>
        <form className="campaign-picker" onSubmit={openCampaign}><label htmlFor="campaign-select">Кампания в Keitaro</label><div><select id="campaign-select" value={selected} onChange={e => setSelected(e.target.value)} required><option value="">Выберите кампанию</option>{campaigns.map(c => <option key={c.id} value={c.id}>#{c.id} · {c.name}</option>)}</select><button className="secondary" disabled={busy || !selected}>Открыть</button><button type="button" className="text-button" disabled={busy} onClick={() => void perform(async () => {setCampaigns(await api<Item[]>('/campaigns'));}).catch(() => {})}>Обновить список</button></div></form>
        {!campaign ? <section className="empty"><div className="empty-icon">↗</div><h2>{campaigns.length ? 'Выберите кампанию' : 'Начните с первой кампании'}</h2><p className="muted">Откройте существующую кампанию или создайте новую.<br/>Изменения офферов останутся черновиком до публикации.</p><button className="secondary" disabled={!catalog} onClick={() => setTab('create')}>Создать кампанию</button></section> : <>
          <header className="campaign-head"><div><span className="eyebrow">КАМПАНИЯ #{campaign.id}</span><h2>{campaign.name}</h2><a href={campaign.admin_url} target="_blank" rel="noreferrer">Открыть в Keitaro ↗</a></div><button className="secondary" disabled={busy || dirty} title={dirty ? 'Сначала опубликуйте или отмените черновики' : 'Получить актуальные потоки из Keitaro'} onClick={() => void perform(async () => {setCampaign(await api<Campaign>(`/campaigns/${campaign.id}/fetch`, 'POST')); setNotice('Потоки загружены. Внешние изменения учтены.');}).catch(() => {})}>↻ Fetch Streams</button></header>
          {dirty && <p className="draft-note">Есть неопубликованные изменения. Fetch станет доступен после публикации или отмены всех черновиков.</p>}
          {campaign.streams.length === 0 && <div className="empty"><h3>В кампании пока нет потоков</h3><p>Добавьте поток в Keitaro, затем нажмите Fetch Streams.</p></div>}
          {catalog && campaign.streams.map(s => <StreamCard key={s.id} stream={s} catalog={catalog} busy={busy} onAction={streamAction}/>)}</>}
      </>}
      <footer>Keitaro Wrapper · FastAPI + SQLAlchemy + Next.js</footer>
    </main></div>;
}
