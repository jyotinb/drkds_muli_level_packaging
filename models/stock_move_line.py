from odoo import models, fields, api, _

class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    # Add loose item weight tracking
    loose_item_weight = fields.Float(string='Loose Item Weight')
    
    # Add packaging specific fields
    packaging_id = fields.Many2one('product.packaging', string='Packaging Type',
                                  domain="[('product_id', '=', product_id)]")
    
    # Track if item was received in vendor packaging
    is_vendor_packaged = fields.Boolean(string="Vendor Packaged", default=False)
    vendor_package_ref = fields.Char(string="Vendor Package Reference")
    
    # Packaging status
    needs_repackaging = fields.Boolean(string="Needs Repackaging", default=False)
    repackaging_note = fields.Text(string="Repackaging Note")
    
    @api.onchange('product_id')
    def _onchange_product_id_packaging(self):
        if self.product_id and self.product_id.packaging_ids:
            # Set default packaging if available
            self.packaging_id = self.product_id.packaging_ids[0].id
    
    @api.onchange('packaging_id', 'qty_done')
    def _onchange_packaging_weight(self):
        """Update loose item weight based on product weight and quantity"""
        if self.product_id and self.qty_done and not self.result_package_id:
            unit_weight = self.product_id.weight or 0.0
            self.loose_item_weight = self.qty_done * unit_weight
    
    def _prepare_auto_package_values(self, packaging, package_name):
        """Prepare values for auto package creation"""
        return {
            'name': package_name,
            'package_type_id': packaging.package_type_id.id if packaging.package_type_id else False,
            'picking_id': self.picking_id.id,
            'packaging_date': fields.Datetime.now(),
            'is_vendor_package': self.is_vendor_packaged,
            'vendor_package_ref': self.vendor_package_ref if self.is_vendor_packaged else False,
        }