from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    # Package identification
    package_prefix = fields.Char(string='Package Prefix')
    
    # Package statistics
    package_count = fields.Integer(string="Package Count", compute='_compute_package_stats')
    primary_package_count = fields.Integer(string="Primary Packages", compute='_compute_package_stats')
    secondary_package_count = fields.Integer(string="Secondary Packages", compute='_compute_package_stats')
    tertiary_package_count = fields.Integer(string="Tertiary Packages", compute='_compute_package_stats')
    
    # Weight tracking
    gross_weight = fields.Float(string="Gross Weight", compute="_compute_weights", store=True)
    net_weight = fields.Float(string="Net Weight", compute="_compute_weights", store=True)
    tare_weight = fields.Float(string="Tare Weight", compute="_compute_weights", store=True)
    weight_uom_name = fields.Char(string="Weight UoM", compute="_compute_weight_uom_name")
    
    # Packaging details
    packing_type = fields.Char(string="Packing Type")
    packaging_notes = fields.Text(string="Packaging Notes")
    
    # Vendor packaging for receipts
    is_vendor_packaging = fields.Boolean(string="Use Vendor Packaging", default=False,
                                        help="Capture vendor packaging information during receipt")
    vendor_package_count = fields.Integer(string="Vendor Packages", compute='_compute_package_stats')
    
    @api.depends('move_line_ids.result_package_id')
    def _compute_package_stats(self):
        for picking in self:
            packages = picking.move_line_ids.mapped('result_package_id')
            picking.package_count = len(packages)
            picking.primary_package_count = len(packages.filtered(lambda p: p.package_level == 'primary'))
            picking.secondary_package_count = len(packages.filtered(lambda p: p.package_level == 'secondary'))
            picking.tertiary_package_count = len(packages.filtered(lambda p: p.package_level == 'tertiary'))
            picking.vendor_package_count = len(packages.filtered(lambda p: p.is_vendor_package))

    @api.depends('move_line_ids', 'move_line_ids.result_package_id', 
                 'move_line_ids.result_package_id.gross_weight', 'move_line_ids.loose_item_weight')
    def _compute_weights(self):
        for picking in self:
            # Get all packages
            packages = picking.move_line_ids.mapped('result_package_id')
            
            # Calculate package weights
            gross_weight = sum(package.gross_weight or 0 for package in packages)
            net_weight = sum(package.net_weight or 0 for package in packages)
            tare_weight = sum(package.tare_weight or 0 for package in packages)
            
            # Add loose item weights
            loose_weight = sum(
                line.loose_item_weight or 0
                for line in picking.move_line_ids
                if not line.result_package_id
            )
            
            # Set the weights
            picking.gross_weight = gross_weight + loose_weight
            picking.net_weight = net_weight + loose_weight
            picking.tare_weight = tare_weight

    @api.depends('company_id')
    def _compute_weight_uom_name(self):
        for picking in self:
            picking.weight_uom_name = picking.company_id.weight_unit_id.name or 'kg'

    def action_create_packages(self):
        self.ensure_one()
        
        # Make package prefix optional
        package_prefix = self.package_prefix or ''
            
        if not self.move_line_ids:
            raise UserError('No move lines found to package.')
            
        # Check if any products have multiple packaging types
        multi_packaging_products = []
        for move_line in self.move_line_ids:
            product = move_line.product_id
            if product and len(product.packaging_ids) > 1:
                multi_packaging_products.append(product.name)
                
        if multi_packaging_products:
            # If multiple packaging types exist, open the multi-packaging wizard
            return {
                'name': ('Select Packaging Types'),
                'type': 'ir.actions.act_window',
                'res_model': 'picking.packaging.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {
                    'default_picking_id': self.id,
                },
            }
        
        # Continue with standard packaging if no product has multiple packaging types
        package_number = 1
        created_packages = self.env['stock.quant.package']
        
        for move_line in self.move_line_ids:
            product = move_line.product_id
            
            # Skip if no product or no packaging defined
            if not product or not product.packaging_ids:
                continue
                
            # Get the first packaging for the product
            packaging = product.packaging_ids[0]
            package_qty = packaging.qty
            total_qty = move_line.quantity
            
            if total_qty <= 0:
                continue
                
            # Calculate number of packages needed
            num_packages = int(total_qty // package_qty)
            remainder_qty = total_qty % package_qty
            
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
                    'picking_id': self.id,
                    'packaging_date': fields.Datetime.now(),
                })
                created_packages |= package
                package_number += 1
                
                # Create quant for the package
                self.env['stock.quant'].create({
                    'product_id': product.id,
                    'quantity': package_qty,
                    'package_id': package.id,
                    'location_id': move_line.location_dest_id.id,
                })
            
            # Handle remainder quantity
            if remainder_qty > 0:
                # Update the move line for the remainder
                move_line.qty_done = remainder_qty
            else:
                # If everything is packaged, archive the move line
                move_line.unlink()
        
        # Return notification with created packages        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Packages Created',
                'message': f'Created {package_number-1} packages',
                'sticky': False,
                'type': 'success',
            }
        }
    
    def action_create_vendor_packages(self):
        """Capture vendor package information during receipt"""
        self.ensure_one()
        
        if self.picking_type_code != 'incoming':
            raise UserError("Vendor packaging can only be captured for receipts.")
            
        return {
            'name': ('Record Vendor Packages'),
            'type': 'ir.actions.act_window',
            'res_model': 'receipt.packaging.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_picking_id': self.id,
                'default_is_vendor_packaging': True,
            },
        }
        
    def action_view_packages(self):
        self.ensure_one()
        return {
            'name': ('Packages'),
            'type': 'ir.actions.act_window',
            'view_mode': 'tree,form',
            'res_model': 'stock.quant.package',
            'domain': [('picking_id', '=', self.id)],
            'context': dict(self.env.context),
        }