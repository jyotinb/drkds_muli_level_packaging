from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging
_logger = logging.getLogger(__name__)

class PickingPackagingWizard(models.TransientModel):
    _name = 'picking.packaging.wizard'
    _description = 'Picking Packaging Wizard'

    picking_id = fields.Many2one('stock.picking', string='Picking', required=True)
    line_ids = fields.One2many('picking.packaging.wizard.line', 'wizard_id', string='Packaging Lines')
    package_prefix = fields.Char(string='Package Prefix')
    
    # Secondary packaging options
    create_secondary_packaging = fields.Boolean(string='Create Secondary Packaging', default=False)
    group_by_product = fields.Boolean(string='Group by Product', default=True,
                                     help="Group packages by product when creating secondary packages")

    @api.model
    def create(self, vals):
        res = super(PickingPackagingWizard, self).create(vals)
        if res.picking_id:
            # Copy the prefix from the picking
            res.package_prefix = res.picking_id.package_prefix
            
            # Create wizard lines for each product with packaging
            for move_line in res.picking_id.move_line_ids:
                product = move_line.product_id
                if product and product.packaging_ids and move_line.qty_done > 0:
                    # Get default packaging (first one)
                    default_packaging = product.packaging_ids[0]
                    
                    # Create wizard line
                    self.env['picking.packaging.wizard.line'].create({
                        'wizard_id': res.id,
                        'product_id': product.id,
                        'qty_to_package': move_line.qty_done,
                        'packaging_id': default_packaging.id,
                        'move_line_id': move_line.id,
                    })
        return res

    def apply_packaging(self):
        self.ensure_one()
        if not self.line_ids:
            return {'warning': {'title': _('Error'), 'message': _('No lines to package')}}
        
        # Update the picking's package prefix if changed
        if self.package_prefix != self.picking_id.package_prefix:
            self.picking_id.package_prefix = self.package_prefix
            
        package_number = 1
        package_prefix = self.package_prefix or ''
        created_packages = self.env['stock.quant.package']
        created_packages_by_product = {}
        
        # Process each line
        for line in self.line_ids:
            if not line.qty_to_package or line.qty_to_package <= 0:
                continue
                
            product = line.product_id
            packaging = line.packaging_id
            
            if not packaging or not packaging.qty:
                continue
                
            # Calculate packages
            package_qty = packaging.qty
            total_qty = line.qty_to_package
            
            num_packages = int(total_qty // package_qty)
            remainder_qty = total_qty % package_qty
            
            line_packages = self.env['stock.quant.package']
            
            # Create full packages
            for _ in range(num_packages):
                # Use product packaging name if prefix is empty
                if not package_prefix and packaging.package_type_id.name:
                    package_name = f"{packaging.package_type_id.name}-{package_number:05d}"
                else:
                    package_name = f"{package_prefix}{package_number:05d}"
                    
                package = self.env['stock.quant.package'].create({
                    'name': package_name,
                    'package_type_id': packaging.package_type_id.id,
                    'picking_id': self.picking_id.id,
                    'packaging_date': fields.Datetime.now(),
                })
                line_packages |= package
                created_packages |= package
                package_number += 1
                
                # Create quant for the package
                self.env['stock.quant'].create({
                    'product_id': product.id,
                    'quantity': package_qty,
                    'package_id': package.id,
                    'location_id': line.move_line_id.location_dest_id.id,
                })
            
            # Keep track of packages by product for secondary packaging
            if product.id not in created_packages_by_product:
                created_packages_by_product[product.id] = line_packages
            else:
                created_packages_by_product[product.id] |= line_packages
            
            # Handle remainder quantity
            if remainder_qty > 0:
                # Update the move line for the remainder
                line.move_line_id.qty_done = remainder_qty
            else:
                # If everything is packaged, archive the move line
                line.move_line_id.unlink()
        
        # Create secondary packages if requested
        if self.create_secondary_packaging and created_packages:
            self._create_secondary_packages(created_packages, created_packages_by_product)
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Packages Created'),
                'message': _('Created %s packages', len(created_packages)),
                'sticky': False,
                'type': 'success',
            }
        }
    
    def _create_secondary_packages(self, primary_packages, packages_by_product):
        """Create secondary packages to contain primary packages"""
        # For each product, find a suitable secondary packaging
        if self.group_by_product:
            for product_id, product_packages in packages_by_product.items():
                if not product_packages:
                    continue
                    
                product = self.env['product.product'].browse(product_id)
                secondary_packaging = self.env['product.packaging'].search([
                    ('product_id', '=', product_id),
                    ('packaging_level', '=', 'secondary')
                ], limit=1)
                
                if not secondary_packaging or secondary_packaging.inner_qty <= 0:
                    continue
                    
                packages_per_secondary = secondary_packaging.inner_qty
                self._group_packages_into_secondary(product_packages, secondary_packaging, packages_per_secondary)
        else:
            # Group all packages together regardless of product
            # Find a generic box packaging type
            box_type = self.env['stock.package.type'].search([('name', 'ilike', 'Box')], limit=1)
            if not box_type:
                # Create a generic box type if none exists
                box_type = self.env['stock.package.type'].create({
                    'name': 'Box',
                    'package_carrier_type': 'none',
                })
                
            # Group packages, 10 per secondary package
            self._group_packages_into_secondary(primary_packages, False, 10, box_type)
    
    def _group_packages_into_secondary(self, packages, secondary_packaging, packages_per_secondary, package_type=None):
        """Group packages into secondary packages with specified capacity"""
        # Group packages into chunks of packages_per_secondary
        package_groups = []
        current_group = self.env['stock.quant.package']
        
        for i, package in enumerate(packages):
            current_group |= package
            if (i + 1) % packages_per_secondary == 0 or i == len(packages) - 1:
                if current_group:
                    package_groups.append(current_group)
                current_group = self.env['stock.quant.package']
        
        # Create secondary packages
        for group in package_groups:
            # Generate package name
            sequence_obj = self.env['ir.sequence'].search([('code', '=', 'stock.package')], limit=1)
            next_number = sequence_obj._next() if sequence_obj else '00001'
            
            if secondary_packaging:
                package_name = f'{secondary_packaging.name}-{next_number}'
                pkg_type_id = secondary_packaging.package_type_id.id if secondary_packaging.package_type_id else False
            else:
                package_name = f'Box-{next_number}'
                pkg_type_id = package_type.id if package_type else False
            
            # Create secondary package
            secondary_package = self.env['stock.quant.package'].create({
                'name': package_name,
                'package_type_id': pkg_type_id,
                'picking_id': self.picking_id.id,
                'packaging_date': fields.Datetime.now(),
            })
            
            # Link primary packages to secondary package
            group.write({'parent_package_id': secondary_package.id})


class PickingPackagingWizardLine(models.TransientModel):
    _name = 'picking.packaging.wizard.line'
    _description = 'Picking Packaging Wizard Line'
    
    wizard_id = fields.Many2one('picking.packaging.wizard', string='Wizard')
    product_id = fields.Many2one('product.product', string='Product', required=True)
    qty_to_package = fields.Float(string='Quantity to Package', required=True)
    packaging_id = fields.Many2one('product.packaging', string='Packaging Type', required=True, 
                                  domain="[('product_id', '=', product_id)]")
    move_line_id = fields.Many2one('stock.move.line', string='Move Line')
    
    @api.onchange('packaging_id')
    def _onchange_packaging_id(self):
        if self.packaging_id and self.packaging_id.qty > 0 and self.qty_to_package:
            # Adjust quantity to match full packages if close enough
            pkg_qty = self.packaging_id.qty
            full_packages = int(self.qty_to_package // pkg_qty)
            remainder = self.qty_to_package % pkg_qty
            
            # If remainder is small, round down to full packages
            if remainder < (pkg_qty * 0.1):  # Less than 10% of a package
                self.qty_to_package = full_packages * pkg_qty