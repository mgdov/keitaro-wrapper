from copy import deepcopy


class RuleError(ValueError):
    pass


def redistribute(entries: list[dict]) -> list[dict]:
    """Integer percentages, stable remainder order, immutable caller data."""
    rows = deepcopy(entries)
    active = [row for row in rows if not row['removed']]
    pinned = [row for row in active if row['pinned_share'] is not None]
    free = [row for row in active if row['pinned_share'] is None]
    total = sum(row['pinned_share'] for row in pinned)
    if any(not 0 <= row['pinned_share'] <= 100 for row in pinned) or total > 100:
        raise RuleError('Сумма закреплённых долей не должна превышать 100%.')
    if not active:
        raise RuleError('В потоке должен остаться хотя бы один активный оффер.')
    if not free and total != 100:
        raise RuleError('Все доли закреплены, но сумма не равна 100%. Освободите одну долю.')
    for row in rows:
        if row['removed']:
            row['share'] = 0
    for row in pinned:
        row['share'] = row['pinned_share']
    if free:
        quotient, remainder = divmod(100 - total, len(free))
        for index, row in enumerate(free):
            row['share'] = quotient + (index < remainder)
    return rows


def payload(entries: list[dict]) -> list[dict]:
    return [dict(offer_id=row['offer_id'], share=row['share'], state='active')
            for row in entries if not row['removed']]


def signature(offers: list[dict]) -> list[tuple]:
    return sorted((int(row['offer_id']), int(row.get('share', 0))) for row in offers
                  if row.get('state', 'active') == 'active')


def merge_remote(previous: list[dict], remote: list[dict], names: dict[int, str]) -> list[dict]:
    rows = deepcopy(previous)
    by_id = {row['offer_id']: row for row in rows}
    seen = set()
    for offer in remote:
        oid = int(offer['offer_id'])
        if oid in seen:
            raise RuleError('API вернул повторяющийся оффер в одном потоке.')
        seen.add(oid)
        row = by_id.get(oid)
        if row is None:
            row = dict(offer_id=oid, name=names.get(oid, f'Оффер #{oid}'), pinned_share=None)
            rows.append(row)
        row.update(name=names.get(oid, row.get('name', f'Оффер #{oid}')),
                   removed=offer.get('state', 'active') != 'active', share=int(offer.get('share', 0)))
        if row['removed']:
            row['share'] = 0
        elif row['pinned_share'] is not None:
            # External weights are authoritative on an explicit Fetch.
            row['pinned_share'] = row['share']
    for row in rows:
        if row['offer_id'] not in seen:
            row.update(removed=True, share=0)
    return rows

