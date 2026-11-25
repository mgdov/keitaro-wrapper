from copy import deepcopy

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import Base


class FakeKeitaro:
    def __init__(self):
        self.campaigns = {1: dict(id=1, name='test_tadzhibov_demo', domain_id=1813, group_id=10332, traffic_source_id=836)}
        self.streams = {
            10: dict(id=10, campaign_id=1, name='Geo', position=1, offers=[], filters=[dict(name='country', payload=['AU'])], action_payload='https://google.com'),
            11: dict(id=11, campaign_id=1, name='Offers', position=2, offers=[dict(offer_id=100, share=50, state='active'), dict(offer_id=101, share=50, state='active')]),
        }
        self.offers = [dict(id=i, name=f'Offer {i}', state='active') for i in range(100, 104)]
        self.calls = []
        self.fail_put = False
        self.lose_ack = False
        self.fail_stream_number = None
        self.created_streams = 0

    def get(self, path):
        return self.request('GET', path)

    def request(self, method, path, data=None):
        self.calls.append((method, path, deepcopy(data)))
        if method == 'GET':
            if path.startswith('/campaigns?'):
                return deepcopy(list(self.campaigns.values()))
            if path == '/offers':
                return deepcopy(self.offers)
            if path.startswith('/offers/'):
                return deepcopy(next(o for o in self.offers if o['id'] == int(path.split('/')[-1])))
            if path == '/domains': return [dict(id=1813, name='test.domain')]
            if path == '/groups?type=campaigns': return [dict(id=10332, name='FORTESTS')]
            if path == '/traffic_sources': return [dict(id=836, name='FORTESTS')]
            if path.endswith('/streams'):
                cid = int(path.split('/')[2])
                return deepcopy([s for s in self.streams.values() if s['campaign_id'] == cid])
            if path.startswith('/campaigns/'):
                return deepcopy(self.campaigns[int(path.split('/')[-1])])
            if path.startswith('/streams/'):
                return deepcopy(self.streams[int(path.split('/')[-1])])
        if method == 'POST' and path == '/campaigns':
            cid = max(self.campaigns) + 1
            self.campaigns[cid] = dict(id=cid, **deepcopy(data))
            return deepcopy(self.campaigns[cid])
        if method == 'POST' and path == '/streams':
            self.created_streams += 1
            if self.created_streams == self.fail_stream_number:
                raise HTTPException(502, 'Simulated failure')
            sid = max(self.streams) + 1
            self.streams[sid] = dict(id=sid, **deepcopy(data))
            return deepcopy(self.streams[sid])
        if method == 'PUT' and path.startswith('/streams/'):
            if self.fail_put:
                raise HTTPException(502, 'Simulated timeout')
            sid = int(path.split('/')[-1])
            self.streams[sid].update(deepcopy(data))
            if self.lose_ack:
                self.lose_ack = False
                raise HTTPException(502, 'Lost acknowledgement')
            return deepcopy(self.streams[sid])
        raise AssertionError((method, path))


@pytest.fixture
def setup(tmp_path):
    remote = FakeKeitaro()
    settings = Settings(database_url=f'sqlite:///{tmp_path}/test.db', keitaro_api_key='test-only')
    app = create_app(settings, remote)
    Base.metadata.create_all(app.state.engine)
    with TestClient(app) as client:
        yield client, remote, app
    app.state.engine.dispose()


def load(client):
    response = client.post('/api/campaigns/1/fetch')
    assert response.status_code == 200, response.text
    return next(s for s in response.json()['streams'] if s['id'] == 11)


def edit(client, stream, action, oid=102, **fields):
    return client.patch('/api/streams/11', json=dict(version=stream['version'], action=action, offer_id=oid, **fields))


def test_create_two_streams_with_prefix_and_settings(setup):
    client, remote, _ = setup
    response = client.post('/api/campaigns', json=dict(name='launch', country='mx', offer_id=100))
    assert response.status_code == 201, response.text
    result = response.json()
    assert result['name'] == 'test_tadzhibov_launch'
    streams = [s for s in remote.streams.values() if s['campaign_id'] == result['id']]
    assert len(streams) == 2
    assert streams[0]['position'] < streams[1]['position']
    assert streams[0]['filters'] == [dict(name='country', mode='accept', payload=['MX'])]
    assert streams[0]['action_payload'] == 'https://google.com'
    assert streams[1]['offers'] == [dict(offer_id=100, share=100, state='active')]
    assert remote.campaigns[result['id']]['domain_id'] == 1813


def test_draft_cancel_and_publish(setup):
    client, remote, _ = setup
    stream = load(client)
    added = edit(client, stream, 'add').json()
    assert added['dirty']
    assert len(remote.streams[11]['offers']) == 2
    assert [o['share'] for o in added['offers']] == [34, 33, 33]
    cancelled = client.post('/api/streams/11/cancel', json=dict(version=added['version'])).json()
    assert len(cancelled['offers']) == 2 and not cancelled['dirty']
    added = edit(client, cancelled, 'add').json()
    published = client.post('/api/streams/11/push', json=dict(version=added['version']))
    assert published.status_code == 200, published.text
    assert not published.json()['dirty']
    assert len(remote.streams[11]['offers']) == 3
    assert client.post('/api/campaigns/1/fetch').status_code == 200
    put = next(c for c in remote.calls if c[0] == 'PUT')
    assert list(put[2]) == ['offers']  # Never overwrite filters or redirect settings.


def test_remove_publish_restore_and_pin(setup):
    client, remote, _ = setup
    stream = edit(client, load(client), 'add').json()
    stream = edit(client, stream, 'pin', oid=100, share=25).json()
    assert [o['share'] for o in stream['offers']] == [25, 38, 37]
    stream = edit(client, stream, 'remove', oid=101).json()
    assert [o['share'] for o in stream['offers']] == [25, 0, 75]
    stream = client.post('/api/streams/11/push', json=dict(version=stream['version'])).json()
    assert len(remote.streams[11]['offers']) == 2
    assert len(stream['offers']) == 3
    stream = edit(client, stream, 'restore', oid=101).json()
    assert [o['share'] for o in stream['offers']] == [25, 38, 37]


def test_fetch_blocks_dirty_and_external_removal_archives(setup):
    client, remote, _ = setup
    stream = edit(client, load(client), 'add').json()
    assert client.post('/api/campaigns/1/fetch').status_code == 409
    client.post('/api/streams/11/cancel', json=dict(version=stream['version']))
    remote.streams[11]['offers'] = [dict(offer_id=100, share=100, state='active')]
    stream = load(client)
    assert stream['offers'][1]['removed'] and stream['offers'][1]['share'] == 0
    stream = edit(client, stream, 'restore', oid=101).json()
    assert [o['share'] for o in stream['offers']] == [50, 50]


def test_stale_version_and_duplicate_add_are_rejected(setup):
    client, _, _ = setup
    original = load(client)
    added = edit(client, original, 'add').json()
    assert edit(client, original, 'remove', oid=100).status_code == 409
    assert edit(client, added, 'add').status_code == 422


def test_failed_publish_retains_draft_and_recovery_is_idempotent(setup):
    client, remote, _ = setup
    stream = edit(client, load(client), 'add').json()
    remote.fail_put = True
    assert client.post('/api/streams/11/push', json=dict(version=stream['version'])).status_code == 502
    current = client.get('/api/campaigns/1').json()['streams'][1]
    assert current['dirty'] and current['version'] == stream['version']
    remote.fail_put = False
    remote.lose_ack = True
    assert client.post('/api/streams/11/push', json=dict(version=stream['version'])).status_code == 502
    before = sum(call[0] == 'PUT' for call in remote.calls)
    result = client.post('/api/streams/11/push', json=dict(version=stream['version']))
    assert result.status_code == 200 and not result.json()['dirty']
    assert before == sum(call[0] == 'PUT' for call in remote.calls)


def test_external_conflict_never_overwrites_remote(setup):
    client, remote, _ = setup
    stream = edit(client, load(client), 'add').json()
    remote.streams[11]['offers'] = [dict(offer_id=103, share=100, state='active')]
    response = client.post('/api/streams/11/push', json=dict(version=stream['version']))
    assert response.status_code == 409
    assert not any(c[0] == 'PUT' for c in remote.calls)


def test_drafts_survive_backend_restart(setup):
    client, remote, original = setup
    stream = edit(client, load(client), 'add').json()
    second = create_app(original.state.settings, remote)
    with TestClient(second) as restarted:
        result = restarted.get('/api/campaigns/1').json()
        assert result['streams'][1]['offers'] == stream['offers']
        assert result['streams'][1]['dirty']
    second.state.engine.dispose()


def test_partial_creation_reports_existing_id_without_automatic_delete(setup):
    client, remote, _ = setup
    remote.fail_stream_number = 2
    result = client.post('/api/campaigns', json=dict(name='partial', country='AU', offer_id=100))
    assert result.status_code == 502
    assert '#2' in result.json()['detail']
    assert 2 in remote.campaigns
    assert not any(c[0] == 'DELETE' for c in remote.calls)


def test_validation_and_empty_flow_protection(setup):
    client, _, _ = setup
    assert client.post('/api/campaigns', json=dict(name=' ', country='AU', offer_id=100)).status_code == 422
    assert client.post('/api/campaigns', json=dict(name='test', country='Australia', offer_id=100)).status_code == 422
    assert client.post('/api/campaigns', json=dict(name='test', country='ZZ', offer_id=100)).status_code == 422
    load(client)
    result = client.patch('/api/streams/10', json=dict(version=1, action='add', offer_id=100))
    assert result.status_code == 422


def test_cross_site_browser_write_rejected(setup):
    client, _, _ = setup
    result = client.post('/api/campaigns/1/fetch', headers={'Sec-Fetch-Site': 'cross-site'})
    assert result.status_code == 403
