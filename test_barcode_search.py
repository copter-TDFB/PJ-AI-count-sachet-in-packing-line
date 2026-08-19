"""Regression tests for BarcodeWorker's stock.picking lookup.

The scanned value is an Odoo **Order Reference** (`x_studio_order_reference`), not a
courier tracking number — see PROJECT_CONTEXT.md. These run with no camera, Odoo, or
network: OdooConn is patched to hand BarcodeWorker a fake XML-RPC `models` object,
following test_invoice_posting.py's RecordingModels pattern.
"""
import pytest

import odoo_counter_app as app


class RecordingModels:
    """Record XML-RPC calls; return no picking so run() exits after the lookup."""

    def __init__(self, picking_rows=()):
        self.calls = []
        self.picking_rows = list(picking_rows)

    def execute_kw(self, database, uid, password, model, method, args, kwargs=None):
        self.calls.append((model, method, args, kwargs or {}))
        if (model, method) == ('stock.picking', 'search_read'):
            return self.picking_rows
        return []

    def picking_search(self):
        """The domain and kwargs of the single stock.picking lookup."""
        call = next(c for c in self.calls if c[:2] == ('stock.picking', 'search_read'))
        return call[2][0], call[3]


@pytest.fixture
def models(monkeypatch):
    recorder = RecordingModels()
    monkeypatch.setattr(app.OdooConn, 'ensure', classmethod(lambda cls: None))
    monkeypatch.setattr(app.OdooConn, '_uid', 7)
    monkeypatch.setattr(app.OdooConn, '_models', recorder)
    return recorder


def _run(barcode):
    app.BarcodeWorker(barcode).run()


def test_lookup_searches_the_order_reference_field(models):
    _run('585617823717230059')

    domain, _ = models.picking_search()
    assert ['x_studio_order_reference', '=', '585617823717230059'] in domain


def test_lookup_no_longer_searches_the_tracking_number(models):
    """A courier tracking number must not resolve a picking — 91% of orders differ."""
    _run('JTTH203159462111')

    domain, kwargs = models.picking_search()
    searched_fields = [term[0] for term in domain if isinstance(term, (list, tuple))]
    assert 'x_studio_tracking_no' not in searched_fields
    # still read back for the Odoo note / debug output, just not searched
    assert 'x_studio_tracking_no' in kwargs['fields']


def test_lookup_keeps_the_pack_and_assigned_filters(models):
    _run('S32015')

    domain, _ = models.picking_search()
    assert ['picking_type_id.name', 'ilike', 'Pack'] in domain
    assert ['state', '=', 'assigned'] in domain


def test_lookup_takes_the_newest_picking_when_an_order_reference_repeats(models):
    """Backorders/splits share an Order Reference; the newest assigned one is the open
    one. Odoo's default picking order is priority/scheduled_date first, so 'id desc'
    has to be explicit."""
    _run('S32015')

    _, kwargs = models.picking_search()
    assert kwargs['order'] == 'id desc'
    assert kwargs['limit'] == 1


def test_lookup_reads_back_the_order_reference(models):
    _run('S32015')

    _, kwargs = models.picking_search()
    assert 'x_studio_order_reference' in kwargs['fields']


def test_barcode_is_stripped_before_searching(models):
    _run('  S32015\t')

    domain, _ = models.picking_search()
    assert ['x_studio_order_reference', '=', 'S32015'] in domain
