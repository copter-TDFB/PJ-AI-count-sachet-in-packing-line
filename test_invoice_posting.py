from odoo_counter_app import _create_and_post_invoice


class RecordingModels:
    """Record XML-RPC calls while supplying the standard invoice-wizard responses."""

    def __init__(self):
        self.calls = []

    def execute_kw(self, database, uid, password, model, method, args, kwargs=None):
        self.calls.append((model, method, args, kwargs or {}))
        if (model, method) == ('sale.advance.payment.inv', 'create'):
            return 9
        if (model, method) == ('sale.order', 'read'):
            return [{'invoice_ids': [101]}]
        if (model, method) == ('ir.actions.server', 'search'):
            return [88]
        return True


def test_auto_created_invoice_sets_sale_order_and_thai_baht_wording_before_posting():
    models = RecordingModels()

    invoice_ids = _create_and_post_invoice(models, uid=7, sale_order_id=42)

    assert invoice_ids == [101]
    calls = models.calls
    write_index = next(
        index for index, call in enumerate(calls)
        if call[:2] == ('account.move', 'write')
    )
    search_index = next(
        index for index, call in enumerate(calls)
        if call[:2] == ('ir.actions.server', 'search')
    )
    run_index = next(
        index for index, call in enumerate(calls)
        if call[:2] == ('ir.actions.server', 'run')
    )
    post_index = next(
        index for index, call in enumerate(calls)
        if call[:2] == ('account.move', 'action_post')
    )

    assert calls[write_index][2] == [[101], {'x_studio_sale_order_id': 42}]
    assert calls[run_index][3]['context'] == {
        'active_model': 'account.move',
        'active_ids': [101],
        'active_id': 101,
    }
    assert write_index < search_index < run_index < post_index
