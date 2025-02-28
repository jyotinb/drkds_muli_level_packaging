from odoo import models, fields, api, _

class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    # Packaging related fields for purchase orders
    packaging_instructions = fields.Text(string='Packaging Instructions', 
                                        help='Special instructions for vendor regarding packaging')
    require_vendor_packages = fields.Boolean(string='Require Vendor Packages', default=False,
                                           help='Require vendor to provide packaging information')
    
    # Package tracking for the purchase
    package_count = fields.Integer(string='Package Count', compute='_compute_package_count')
    
    def _compute_package_count(self):
        for order in self:
            order.package_count = self.env['stock.quant.package'].search_count([
                ('purchase_id', '=', order.id)
            ])
    
    def action_view_packages(self):
        self.ensure_one()
        return {
            'name': _('Packages'),
            'type': 'ir.actions.act_window',
            'view_mode': 'tree,form',
            'res_model': 'stock.quant.package',
            'domain': [('purchase_id', '=', self.id)],
            'context': dict(self.env.context),
        }


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'
    
    # Packaging details for each line
    packaging_id = fields.Many2one('product.packaging', string='Preferred Packaging',
                                  domain="[('product_id', '=', product_id), ('is_vendor_packaging', '=', True)]")
    
    # Expected package count
    expected_package_count = fields.Integer(string='Expected Packages', compute='_compute_expected_packages')
    
    @api.depends('product_qty', 'packaging_id')
    def _compute_expected_packages(self):
        for line in self:
            if line.packaging_id and line.packaging_id.qty > 0:
                line.expected_package_count = int(line.product_qty / line.packaging_id.qty)
                if line.product_qty % line.packaging_id.qty > 0:
                    line.expected_package_count += 1
            else:
                line.expected_package_count = 0
    
    @api.onchange('product_id')
    def _onchange_product_id_packaging(self):
        if self.product_id:
            # Try to find vendor-specific packaging first
            vendor_packaging = self.env['product.packaging'].search([
                ('product_id', '=', self.product_id.id),
                ('is_vendor_packaging', '=', True),
                ('vendor_ids', 'in', self.order_id.partner_id.id)
            ], limit=1)
            
            if vendor_packaging:
                self.packaging_id = vendor_packaging.id
            elif self.product_id.packaging_ids:
                # Otherwise use any packaging available
                self.packaging_id = self.product_id.packaging_ids[0].id