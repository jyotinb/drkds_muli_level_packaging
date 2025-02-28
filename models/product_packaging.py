from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class ProductPackaging(models.Model):
    _inherit = 'product.packaging'

    # Enhanced fields for packaging
    packaging_level = fields.Selection([
        ('primary', 'Primary'),
        ('secondary', 'Secondary'),
        ('tertiary', 'Tertiary')
    ], string="Packaging Level", default='primary', 
       help="Primary: Direct product packaging\nSecondary: Packaging for multiple primary packages\nTertiary: Transport packaging (pallets, etc.)")
    
    inner_qty = fields.Integer(string="Inner Packages Quantity", default=0,
                              help="Number of primary packages this package can contain")
    
    parent_id = fields.Many2one('product.packaging', string="Parent Packaging", 
                               domain="[('packaging_level', '!=', 'primary'), ('product_id', '=', product_id)]")
    
    material = fields.Char(string="Packaging Material")
    
    is_vendor_packaging = fields.Boolean(string="Vendor Packaging", default=False,
                                        help="This packaging is used by vendors for this product")
    
    vendor_ids = fields.Many2many('res.partner', string="Vendors",
                                 domain="[('supplier_rank', '>', 0)]")
    
    barcode = fields.Char(string="Packaging Barcode")
    
    # Package weight calculation
    tare_weight = fields.Float(string="Tare Weight", help="Weight of empty packaging")
    max_weight = fields.Float(string="Maximum Weight", help="Maximum weight this packaging can hold")
    
    @api.constrains('packaging_level', 'parent_id')
    def _check_packaging_hierarchy(self):
        for packaging in self:
            if packaging.parent_id:
                if packaging.packaging_level == 'tertiary':
                    raise ValidationError(_("Tertiary packaging cannot have a parent packaging."))
                if packaging.parent_id.packaging_level == 'primary':
                    raise ValidationError(_("Primary packaging cannot contain other packaging."))
                if packaging.packaging_level == packaging.parent_id.packaging_level:
                    raise ValidationError(_("Parent packaging must be at a higher level than this packaging."))

    @api.constrains('qty', 'inner_qty')
    def _check_quantities(self):
        for packaging in self:
            if packaging.qty <= 0:
                raise ValidationError(_("Package quantity must be positive."))
            if packaging.packaging_level != 'primary' and packaging.inner_qty <= 0:
                raise ValidationError(_("Inner packages quantity must be positive for non-primary packaging."))