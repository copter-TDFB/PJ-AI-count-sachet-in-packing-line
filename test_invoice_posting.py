from odoo_counter_app import _amount_to_thai_baht_text, _create_and_post_invoice, _resolve_documents_to_print


class RecordingModels:
    """Record XML-RPC calls while supplying the standard invoice-wizard responses."""

    def __init__(self, thai_baht_write_error=None):
        self.calls = []
        self.thai_baht_write_error = thai_baht_write_error

    def execute_kw(self, database, uid, password, model, method, args, kwargs=None):
        self.calls.append((model, method, args, kwargs or {}))
        if (model, method) == ('sale.advance.payment.inv', 'create'):
            return 9
        if (model, method) == ('sale.order', 'read'):
            return [{'invoice_ids': [101]}]
        if (model, method) == ('account.move', 'read'):
            return [{'id': 101, 'amount_total': 3690.0}]
        if (model, method) == ('account.move', 'write') and 'x_studio_thai_bahttext' in args[1] \
                and self.thai_baht_write_error:
            raise self.thai_baht_write_error
        return True


def test_auto_created_invoice_sets_sale_order_and_thai_baht_wording_before_posting():
    models = RecordingModels()

    invoice_ids = _create_and_post_invoice(models, uid=7, sale_order_id=42)

    assert invoice_ids == [101]
    calls = models.calls
    link_index = next(
        index for index, call in enumerate(calls)
        if call[:2] == ('account.move', 'write') and call[2][1] == {'x_studio_sale_order_id': 42}
    )
    wording_index = next(
        index for index, call in enumerate(calls)
        if call[:2] == ('account.move', 'write') and 'x_studio_thai_bahttext' in call[2][1]
    )
    post_index = next(
        index for index, call in enumerate(calls)
        if call[:2] == ('account.move', 'action_post')
    )

    assert calls[wording_index][2] == [[101], {'x_studio_thai_bahttext': _amount_to_thai_baht_text(3690.0)}]
    assert ('ir.actions.server', 'run') not in [call[:2] for call in calls]
    assert link_index < wording_index < post_index


def test_thai_baht_write_failure_leaves_auto_created_invoice_unposted(capsys):
    models = RecordingModels(thai_baht_write_error=RuntimeError('write failed'))

    invoice_ids = _create_and_post_invoice(models, 7, 42)

    assert invoice_ids is None
    assert ('account.move', 'action_post') not in [call[:2] for call in models.calls]
    assert 'write failed' in capsys.readouterr().out


def test_resolve_documents_to_print_cash_value_returns_single_report():
    cfg = {
        'need_bill_value': 'ปริ้นใบเสร็จ',
        'need_bill_credit_value': 'ปริ้นใบกำกับ (เครดิต)',
        'report_id': 1204,
        'cr_report_id': 1200,
    }

    assert _resolve_documents_to_print('ปริ้นใบเสร็จ', cfg) == [(1204, '1204')]


def test_resolve_documents_to_print_credit_value_returns_only_cr_report():
    cfg = {
        'need_bill_value': 'ปริ้นใบเสร็จ',
        'need_bill_credit_value': 'ปริ้นใบกำกับ (เครดิต)',
        'report_id': 1204,
        'cr_report_id': 1200,
    }

    assert _resolve_documents_to_print('ปริ้นใบกำกับ (เครดิต)', cfg) == [(1200, 'Cr.(1200)')]


def test_resolve_documents_to_print_unrelated_value_returns_empty_list():
    cfg = {
        'need_bill_value': 'ปริ้นใบเสร็จ',
        'need_bill_credit_value': 'ปริ้นใบกำกับ (เครดิต)',
        'report_id': 1204,
        'cr_report_id': 1200,
    }

    assert _resolve_documents_to_print('', cfg) == []
    assert _resolve_documents_to_print('บางค่าอื่นที่ไม่เกี่ยว', cfg) == []


def test_resolve_documents_to_print_honors_config_overrides_not_hardcoded_defaults():
    cfg = {
        'need_bill_value': 'CASH',
        'need_bill_credit_value': 'CREDIT',
        'report_id': 111,
        'cr_report_id': 222,
    }

    assert _resolve_documents_to_print('CASH', cfg) == [(111, '111')]
    assert _resolve_documents_to_print('CREDIT', cfg) == [(222, 'Cr.(222)')]
