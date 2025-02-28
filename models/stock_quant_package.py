from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class StockQuantPackage(models.Model):
    _inherit = 'stock.quant.package'

    # Source tracking fields
    mo_id = fields.Many2one('mrp.production', string='Manufacturing Order')
    picking_id = fields.Many2one('stock.picking', string='Transfer')
    purchase_id = fields.Many2one('purchase.order', string='Purchase Order')
    
    # Package content details
    content_details = fields.Text(string="Package Contents", compute="_compute_content_details", store=True)
    product_count = fields.Integer(string="Product Count", compute="_compute_product_stats", store=True)
    total_quantity = fields.Float(string="Total Quantity", compute="_compute_product_stats", store=True)
    
    # Package weight management
    gross_weight = fields.Float(string="Gross Weight", compute="_compute_weights", store=True)
    net_weight = fields.Float(string="Net Weight", compute="_compute_weights", store=True)
    tare_weight = fields.Float(string="Tare Weight", related="package_type_id.base_weight", readonly=True)
    
    # Packaging hierarchy fields
    parent_package_id = fields.Many2one('stock.quant.package', string="Parent Package")
    child_package_ids = fields.One2many('stock.quant.package', 'parent_package_id', string="Contained Packages")
    package_level = fields.Selection([
        ('primary', 'Primary'),
        ('secondary', 'Secondary'),
        ('tertiary', 'Tertiary')
    ], string="Package Level", compute="_compute_package_level", store=True)
    
    # Quality related fields
    quality_state = fields.Selection([
        ('draft', 'Draft'),
        ('pending', 'Pending Inspection'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected')
    ], string="Quality Status", default='draft')
    
    # Tracking fields
    packaging_date = fields.Datetime(string="Packaging Date", default=fields.Datetime.now)
    vendor_package_ref = fields.Char(string="Vendor Package Reference")
    is_vendor_package = fields.Boolean(string="Vendor Package", default=False)
    
    @api.depends('quant_ids', 'child_package_ids', 'child_package_ids.quant_ids')
    def _compute_content_details(self):
        for package in self:
            details = []
            
            # Add direct quants
            for quant in package.quant_ids:
                if quant.product_id and quant.product_uom_id:
                    product_code = quant.product_id.default_code or ''
                    details.append(f'[{product_code}] {quant.product_id.name} - {quant.quantity} {quant.product_uom_id.name}')
            
            # Add quants from child packages
            for child in package.child_package_ids:
                for quant in child.quant_ids:
                    if quant.product_id and quant.product_uom_id:
                        product_code = quant.product_id.default_code or ''
                        details.append(f'[{product_code}] {quant.product_id.name} - {quant.quantity} {quant.product_uom_id.name} (in {child.name})')
            
            package.content_details = "\n".join(details) if details else False
    
    @api.depends('quant_ids', 'quant_ids.product_id', 'quant_ids.quantity', 
                 'child_package_ids', 'child_package_ids.quant_ids')
    def _compute_product_stats(self):
        for package in self:
            # Direct products in this package
            direct_products = package.quant_ids.mapped('product_id')
            direct_quantity = sum(package.quant_ids.mapped('quantity'))
            
            # Products in child packages
            child_products = self.env['product.product']
            child_quantity = 0.0
            
            for child in package.child_package_ids:
                child_products |= child.quant_ids.mapped('product_id')
                child_quantity += sum(child.quant_ids.mapped('quantity'))
            
            # Combine unique products from this package and all child packages
            all_products = direct_products | child_products
            
            package.product_count = len(all_products)
            package.total_quantity = direct_quantity + child_quantity
    
    @api.depends('quant_ids.quantity', 'quant_ids.product_id.weight', 
                 'package_type_id.base_weight', 'child_package_ids')
    def _compute_weights(self):
        for package in self:
            # Calculate product weight
            product_weight = sum(
                quant.quantity * quant.product_id.weight 
                for quant in package.quant_ids 
                if quant.product_id and quant.product_id.weight
            )
            
            # Add weights of any child packages
            child_weight = sum(child.gross_weight for child in package.child_package_ids)
            
            # Calculate tare weight (packaging material)
            tare_weight = package.package_type_id.base_weight if package.package_type_id else 0.0
            
            package.net_weight = product_weight + child_weight
            package.gross_weight = package.net_weight + tare_weight
    
    @api.depends('parent_package_id', 'child_package_ids')
    def _compute_package_level(self):
        for package in self:
            if package.parent_package_id:
                # This is inside another package
                if package.child_package_ids:
                    package.package_level = 'secondary'
                else:
                    package.package_level = 'primary'
            else:
                # Top level package
                if package.child_package_ids:
                    package.package_level = 'tertiary'
                else:
                    package.package_level = 'primary'
    
    @api.model
    def create(self, vals):
        # Generate custom pack code if name not provided
        if 'name' not in vals or not vals['name']:
            # Get packaging type if available for more specific naming
            packaging_type_name = "Pack"
            if vals.get('package_type_id'):
                package_type = self.env['stock.package.type'].browse(vals['package_type_id'])
                if package_type and package_type.name:
                    packaging_type_name = package_type.name
            
            # Get next sequence number
            sequence_obj = self.env['ir.sequence'].search([('code', '=', 'stock.package')], limit=1)
            next_number = sequence_obj._next() if sequence_obj else '00001'
            
            vals['name'] = f"{packaging_type_name}-{next_number}"
        
        return super(StockQuantPackage, self).create(vals)
    
    def action_set_quality_pending(self):
        self.write({'quality_state': 'pending'})
    
    def action_approve_quality(self):
        self.write({'quality_state': 'approved'})
    
    def action_reject_quality(self):
        self.write({'quality_state': 'rejected'})
    
    def action_view_contained_packages(self):
        self.ensure_one()
        return {
            'name': _('Contained Packages'),
            'type': 'ir.actions.act_window',
            'res_model': 'stock.quant.package',
            'view_mode': 'tree,form',
            'domain': [('parent_package_id', '=', self.id)],
        }
    
    def action_print_package_label(self):
        self.ensure_one()
        return {
            'name': _('Package Label'),
            'type': 'ir.actions.report',
            'report_name': 'advanced_auto_packaging.report_package_label',
            'report_type': 'qweb-pdf',
            'model': 'stock.quant.package',
            'res_id': self.id,
        }
