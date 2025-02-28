from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging
_logger = logging.getLogger(__name__)

class SecondaryPackagingWizard(models.TransientModel):
    _name = 'secondary.packaging.wizard'
    _description = 'Secondary Packaging Wizard'

    # Source reference (either MO or Picking)
    production_id = fields.Many2one('mrp.production', string='Manufacturing Order')
    picking_id = fields.Many2one('stock.picking', string='Transfer')
    
    # Packaging configuration
    secondary_package_type_id = fields.Many2one('product.packaging', string='Secondary Package Type', required=True,
                                               domain="[('packaging_level', '=', 'secondary')]")
    packages_per_secondary = fields.Integer(string='Packages per Box', default=1, required=True)
    group_by_product = fields.Boolean(string='Group by Product', default=True)
    
    # Selected packages
    available_package_ids = fields.Many2many('stock.quant.package', string='Available Packages',
                                           compute='_compute_available_packages')
    selected_package_ids = fields.Many2many('stock.quant.package', 'secondary_wizard_package_rel',
                                          'wizard_id', 'package_id', string='Selected Packages')
    
    @api.depends('production_id', 'picking_id')
    def _compute_available_packages(self):
        for wizard in self:
            domain = [
                ('parent_package_id', '=', False),  # Only primary packages
                ('package_level', '=', 'primary')
            ]
            
            if wizard.production_id:
                domain.append(('mo_id', '=', wizard.production_id.id))
            elif wizard.picking_id:
                domain.append(('picking_id', '=', wizard.picking_id.id))
            
            wizard.available_package_ids = self.env['stock.quant.package'].search(domain)
    
    @api.onchange('production_id', 'picking_id')
    def _onchange_source(self):
        # When source changes, update available packages and select all
        self.selected_package_ids = [(6, 0, self.available_package_ids.ids)]
    
    @api.onchange('secondary_package_type_id')
    def _onchange_secondary_package_type(self):
        if self.secondary_package_type_id and self.secondary_package_type_id.inner_qty > 0:
            self.packages_per_secondary = self.secondary_package_type_id.inner_qty
    
    def create_secondary_packages(self):
        self.ensure_one()
        
        if not self.selected_package_ids:
            return {'warning': {'title': _('Error'), 'message': _('No packages selected')}}
        
        if self.packages_per_secondary <= 0:
            return {'warning': {'title': _('Error'), 'message': _('Packages per box must be greater than zero')}}
        
        packages_by_product = {}
        
        # Group packages by product if requested
        if self.group_by_product:
            for package in self.selected_package_ids:
                product_ids = package.quant_ids.mapped('product_id.id')
                
                # Skip packages with multiple products
                if len(product_ids) != 1:
                    continue
                    
                product_id = product_ids[0]
                if product_id not in packages_by_product:
                    packages_by_product[product_id] = self.env['stock.quant.package']
                
                packages_by_product[product_id] |= package
            
            # Create secondary packages for each product group
            created_secondary = self.env['stock.quant.package']
            for product_id, packages in packages_by_product.items():
                secondary_packages = self._create_secondary_packages_for_group(packages)
                created_secondary |= secondary_packages
                
            if not created_secondary:
                # Handle packages that weren't processed
                remaining_packages = self.selected_package_ids - self.env['stock.quant.package'].search([
                    ('id', 'in', self.selected_package_ids.ids),
                    ('parent_package_id', '!=', False)
                ])
                
                if remaining_packages:
                    secondary_packages = self._create_secondary_packages_for_group(remaining_packages)
                    created_secondary |= secondary_packages
        else:
            # Create secondary packages without grouping by product
            created_secondary = self._create_secondary_packages_for_group(self.selected_package_ids)
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Secondary Packages Created'),
                'message': _('Created %s secondary packages', len(created_secondary)),
                'sticky': False,
                'type': 'success',
            }
        }
    
    def _create_secondary_packages_for_group(self, packages):
        """Create secondary packages for a group of packages"""
        if not packages:
            return self.env['stock.quant.package']
        
        # Split packages into groups based on packages_per_secondary
        package_groups = []
        current_group = self.env['stock.quant.package']
        
        for i, package in enumerate(packages):
            current_group |= package
            if (i + 1) % self.packages_per_secondary == 0 or i == len(packages) - 1:
                if current_group:
                    package_groups.append(current_group)
                current_group = self.env['stock.quant.package']
        
        # Create a secondary package for each group
        created_packages = self.env['stock.quant.package']
        
        for group in package_groups:
            # Get next sequence number
            sequence_obj = self.env['ir.sequence'].search([('code', '=', 'stock.package')], limit=1)
            next_number = sequence_obj._next() if sequence_obj else '00001'
            
            # Create package name
            package_name = f'{self.secondary_package_type_id.name}-{next_number}'
            
            # Set metadata from source
            mo_id = False
            picking_id = False
            if self.production_id:
                mo_id = self.production_id.id
            elif self.picking_id:
                picking_id = self.picking_id.id
            
            # Create secondary package
            secondary_package = self.env['stock.quant.package'].create({
                'name': package_name,
                'package_type_id': self.secondary_package_type_id.package_type_id.id,
                'mo_id': mo_id,
                'picking_id': picking_id,
                'packaging_date': fields.Datetime.now(),
            })
            
            created_packages |= secondary_package
            
            # Link primary packages to secondary package
            group.write({'parent_package_id': secondary_package.id})
        
        return created_packages