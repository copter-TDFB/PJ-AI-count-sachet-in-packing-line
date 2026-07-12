"""Read-only KAN-53 spike: inspect sale-order fields usable as shop identity."""

import ast
import re
import xmlrpc.client
from pathlib import Path

APP_PATH = Path(__file__).resolve().parents[1] / 'odoo_counter_app.py'


def odoo_constants():
    tree = ast.parse(APP_PATH.read_text(encoding='utf-8'))
    values = {}
    wanted = {'ODOO_URL', 'ODOO_DB', 'ODOO_USER', 'ODOO_PASSWORD'}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in wanted:
                    values[target.id] = node.value.value
    return values


def platform_hint(origin):
    origin = origin or ''
    if re.match(r'^(S\d+|MZS-\d+)', origin, re.I):
        return 'shopee'
    if 'tiktok' in origin.lower():
        return 'tiktok'
    if 'lazada' in origin.lower():
        return 'lazada'
    return 'other'


def main():
    constants = odoo_constants()
    url = constants['ODOO_URL']
    db = constants['ODOO_DB']
    user = constants['ODOO_USER']
    password = constants['ODOO_PASSWORD']
    common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
    uid = common.authenticate(db, user, password, {})
    if not uid:
        raise RuntimeError('Odoo login failed')
    models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object')

    fields = models.execute_kw(
        db, uid, password, 'sale.order', 'fields_get', [],
        {'attributes': ['type', 'string']},
    )
    candidates = [
        name for name in ('team_id', 'tag_ids', 'warehouse_id') if name in fields
    ]
    candidates.extend(sorted(name for name in fields if name.startswith('x_studio_')))
    print('sale.order candidate fields:', ', '.join(candidates) or '(none)')

    pickings = models.execute_kw(
        db, uid, password, 'stock.picking', 'search_read',
        [[['picking_type_id.name', 'ilike', 'Pack'], ['origin', '!=', False], ['sale_id', '!=', False]]],
        {'fields': ['name', 'origin', 'sale_id'], 'order': 'id desc', 'limit': 60},
    )
    selected = []
    seen_hints = set()
    for picking in pickings:
        hint = platform_hint(picking.get('origin'))
        if hint not in seen_hints or len(selected) < 8:
            selected.append(picking)
            seen_hints.add(hint)
        if len(selected) == 12:
            break

    for picking in selected:
        sale_id = picking['sale_id'][0]
        sale = models.execute_kw(
            db, uid, password, 'sale.order', 'read', [[sale_id]],
            {'fields': candidates},
        )[0]
        print('\n{hint}: picking={picking} origin={origin!r} sale_id={sale_id}'.format(
            hint=platform_hint(picking.get('origin')),
            picking=picking['name'], origin=picking['origin'], sale_id=sale_id,
        ))
        for field in candidates:
            print('  {field}: {value!r}'.format(field=field, value=sale.get(field)))


if __name__ == '__main__':
    main()
