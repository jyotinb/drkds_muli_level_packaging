from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging
_logger = logging.getLogger(__name__)

class PackagingWizard(models.TransientModel):
    _name = 'packaging.wizard'
    _description = 'Packaging Wizard for Manufacturing Orders'

    package_type_id = fields.Many2one(
        'product.packaging', 
        string='Package Type', 
        required=True, 
        domain="[('product_id', '=', product_id)]"
    )
    package_qty = fields.Float(string='Quantity to Pack', required=True)
    production_id = fields.Many2one('mrp.production', string='Manufacturing Order', required=True)
    product_id = fields.Many2one('product.product', string='Product', required=True)
    available_qty = fields.Float(string='Available Quantity', readonly=True)
    
    # Packaging hierarchy options
    create_secondary_packaging = fields.Boolean(string='Create Secondary Packaging', default=False)
    secondary_package_type_id = fields.Many2one(
        'product.packaging',
        string='Secondary Package Type',
        domain="[('product_id', '=', product_id), ('packaging_level', '=', 'secondary')]"
    )
    packages_per_secondary = fields.Integer(string='Packages per Box', default=0)
    
    @api.onchange('production_id')
    def _onchange_production_id(self):
        if self.production_id:
            self.product_id = self.production_id.product_id.id
            self.available_qty = self.production_id.product_qty - self.production_id.qty_packaged
            self.package_qty = self.available_qty

    @api.onchange('package_type_id')
    def _onchange_package_type_id(self):
        if self.package_type_id and self.package_type_id.qty:
            # Suggest packaging in multiples of the packaging quantity
            pkg_qty = self.package_type_id.qty
            full_packages = int(self.available_qty // pkg_qty)
            self.package_qty = full_packages * pkg_qty
            
            # Check if secondary packaging is available
            secondary_packaging = self.env['product.packaging'].search([
                ('product_id', '=', self.product_id.id),
                ('packaging_level', '=', 'secondary')
            ], limit=1)
            
            if secondary_packaging:
                self.secondary_package_type_id = secondary_packaging.id
                if secondary_packaging.inner_qty > 0:
                    self.packages_per_secondary = secondary_packaging.inner_qty

    @api.onchange('create_secondary_packaging', 'secondary_package_type_id')
    def _onchange_secondary_packaging(self):
        if self.create_secondary_packaging and self.secondary_package_type_id:
            if self.secondary_package_type_id.inner_qty > 0:
                self.packages_per_secondary = self.secondary_package_type_id.inner_qty

    def apply_packaging(self):
        self.ensure_one()
        
        if self.package_qty <= 0:
            return {'warning': {'title': _('Error'), 'message': _('Quantity must be greater than zero')}}
            
        if self.package_qty > self.available_qty:
            return {'warning': {'title': _('Error'), 'message': _('Cannot package more than available quantity')}}
            
        # Create primary packages
        primary_packages = self.production_id.create_packages(self.package_type_id.id, self.package_qty)
        
        # Create secondary packages if requested
        if self.create_secondary_packaging and self.secondary_package_type_id and self.packages_per_secondary > 0:
            self._create_secondary_packages(primary_packages)
        
        # Return to the production form
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'mrp.production',
            'res_id': self.production_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
        
    def _create_secondary_packages(self, primary_packages):
        """Group primary packages into secondary packages"""
        if not primary_packages or not self.packages_per_secondary:
            return
            
        # Group packages by packages_per_secondary
        package_groups = []
        current_group = self.env['stock.quant.package']
        
        for i, package in enumerate(primary_packages):
            current_group |= package
            if (i + 1) % self.packages_per_secondary == 0 or i == len(primary_packages) - 1:
                package_groups.append(current_group)
                current_group = self.env['stock.quant.package']
        
        # Create a secondary package for each group
        for group in package_groups:
            if not group:
                continue
                
            # Generate package name
            sequence_obj = self.env['ir.sequence'].search([('code', '=', 'stock.package')], limit=1)
            next_number = sequence_obj._next() if sequence_obj else '00001'
            package_name = f'{self.secondary_package_type_id.name}-{next_number}'
            
            # Create secondary package
            secondary_package = self.env['stock.quant.package'].create({
                'name': package_name,
                'package_type_id': self.secondary_package_type_id.package_type_id.id,
                'mo_id': self.production_id.id,
                'packaging_date': fields.Datetime.now(),
            })
            
            # Associate primary packages with the secondary package
            group.write({'parent_package_id': secondary_package.id})