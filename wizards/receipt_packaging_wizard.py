from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging
_logger = logging.getLogger(__name__)

class ReceiptPackagingWizard(models.TransientModel):
    _name = 'receipt.packaging.wizard'
    _description = 'Receipt Packaging Wizard'

    picking_id = fields.Many2one('stock.picking', string='Receipt', required=True, 
                                domain="[('picking_type_code', '=', 'incoming')]")
    line_ids = fields.One2many('receipt.packaging.wizard.line', 'wizard_id', string='Packaging Lines')
    is_vendor_packaging = fields.Boolean(string='Vendor Packaging', default=False)
    auto_create_vendor_packaging = fields.Boolean(string='Auto-Create Vendor Packaging', default=False,
                                                help="Automatically create vendor packaging types if they don't exist")
    repackage_after_receipt = fields.Boolean(string='Repackage After Receipt', default=False,
                                           help="Repackage items into standard company packaging after receipt")
    quality_check_required = fields.Boolean(string='Quality Check Required', default=True)

    @api.model
    def create(self, vals):
        res = super(ReceiptPackagingWizard, self).create(vals)
        if res.picking_id:
            # Create wizard lines for each product in the receipt
            for move_line in res.picking_id.move_line_ids:
                product = move_line.product_id
                if product and move_line.qty_done > 0:
                    # Try to find vendor packaging first
                    packaging = False
                    if res.picking_id.partner_id:
                        vendor_packaging = self.env['product.packaging'].search([
                            ('product_id', '=', product.id),
                            ('is_vendor_packaging', '=', True),
                            ('vendor_ids', 'in', res.picking_id.partner_id.id)
                        ], limit=1)
                        
                        if vendor_packaging:
                            packaging = vendor_packaging
                    
                    # Otherwise use any available packaging
                    if not packaging and product.packaging_ids:
                        packaging = product.packaging_ids[0]
                    
                    # Create wizard line
                    vals = {
                        'wizard_id': res.id,
                        'product_id': product.id,
                        'received_qty': move_line.qty_done,
                        'move_line_id': move_line.id,
                        'is_vendor_packaged': res.is_vendor_packaging,
                    }
                    
                    if packaging:
                        vals['packaging_id'] = packaging.id
                        # Calculate package count based on packaging quantity
                        if packaging.qty > 0:
                            vals['package_count'] = int(move_line.qty_done // packaging.qty)
                            if move_line.qty_done % packaging.qty > 0:
                                vals['package_count'] += 1
                    
                    self.env['receipt.packaging.wizard.line'].create(vals)
        return res

    def apply_packaging(self):
        self.ensure_one()
        if not self.line_ids:
            return {'warning': {'title': _('Error'), 'message': _('No lines to package')}}
        
        created_packages = self.env['stock.quant.package']
        
        # Process each line
        for line in self.line_ids:
            if not line.is_vendor_packaged and not line.packaging_id:
                # Skip lines that are not vendor packaged and have no packaging type
                continue
            
            # Create new vendor packaging type if needed
            if self.auto_create_vendor_packaging and line.is_vendor_packaged and not line.packaging_id:
                packaging = self._create_vendor_packaging(line)
                line.packaging_id = packaging.id
            
            # Skip if still no packaging
            if not line.packaging_id:
                continue
                
            # Calculate package quantities
            total_qty = line.received_qty
            package_qty = line.packaging_id.qty
            packages_to_create = line.package_count
            
            if package_qty <= 0 or packages_to_create <= 0:
                continue
                
            # Create packages based on package count
            line_packages = self._create_packages_for_line(line, packages_to_create)
            created_packages |= line_packages
            
            # Set move line as vendor packaged if applicable
            if line.is_vendor_packaged and line.move_line_id:
                line.move_line_id.is_vendor_packaged = True
                line.move_line_id.vendor_package_ref = line.vendor_package_ref or ''
                
            # Mark for repackaging if needed
            if self.repackage_after_receipt and line.move_line_id:
                line.move_line_id.needs_repackaging = True
                if line.repackaging_note:
                    line.move_line_id.repackaging_note = line.repackaging_note
        
        # Set quality check status if needed
        if self.quality_check_required and created_packages:
            created_packages.write({'quality_state': 'pending'})
        
        # Link packages to purchase order if applicable
        purchase_id = self.picking_id.purchase_id
        if purchase_id and created_packages:
            created_packages.write({'purchase_id': purchase_id.id})
        
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
    
    def _create_vendor_packaging(self, line):
        """Create a new vendor packaging type for this product"""
        # Try to determine a meaningful name for the packaging
        packaging_name = f"{self.picking_id.partner_id.name}'s {line.product_id.name} packaging"
        
        # Create a package type if needed
        package_type = self.env['stock.package.type'].search([('name', '=', 'Vendor Package')], limit=1)
        if not package_type:
            package_type = self.env['stock.package.type'].create({
                'name': 'Vendor Package',
                'package_carrier_type': 'none',
            })
        
        # Estimate a reasonable package quantity if none provided
        estimated_qty = line.received_qty / line.package_count if line.package_count else line.received_qty
        
        # Create the packaging record
        return self.env['product.packaging'].create({
            'name': packaging_name,
            'product_id': line.product_id.id,
            'qty': estimated_qty,
            'package_type_id': package_type.id,
            'is_vendor_packaging': True,
            'vendor_ids': [(4, self.picking_id.partner_id.id)] if self.picking_id.partner_id else False,
        })
    
    def _create_packages_for_line(self, line, package_count):
        """Create specified number of packages for a line"""
        created_packages = self.env['stock.quant.package']
        
        # Calculate quantity per package (evenly distributed)
        total_qty = line.received_qty
        qty_per_package = total_qty / package_count if package_count else total_qty
        
        for i in range(package_count):
            # For the last package, use remaining quantity
            is_last_package = (i == package_count - 1)
            current_qty = total_qty - (qty_per_package * i) if is_last_package else qty_per_package
            
            # Create package
            package_data = {
                'package_type_id': line.packaging_id.package_type_id.id if line.packaging_id.package_type_id else False,
                'picking_id': self.picking_id.id,
                'packaging_date': fields.Datetime.now(),
                'is_vendor_package': line.is_vendor_packaged,
            }
            
            # Use vendor package reference if provided
            if line.is_vendor_packaged and line.vendor_package_ref:
                if package_count > 1:
                    package_data['vendor_package_ref'] = f"{line.vendor_package_ref}-{i+1}"
                    package_data['name'] = f"VENDOR-{line.vendor_package_ref}-{i+1}"
                else:
                    package_data['vendor_package_ref'] = line.vendor_package_ref
                    package_data['name'] = f"VENDOR-{line.vendor_package_ref}"
            
            package = self.env['stock.quant.package'].create(package_data)
            created_packages |= package
            
            # Create quant for the package
            self.env['stock.quant'].create({
                'product_id': line.product_id.id,
                'quantity': current_qty,
                'package_id': package.id,
                'location_id': line.move_line_id.location_dest_id.id,
            })
            
        return created_packages


class ReceiptPackagingWizardLine(models.TransientModel):
    _name = 'receipt.packaging.wizard.line'
    _description = 'Receipt Packaging Wizard Line'
    
    wizard_id = fields.Many2one('receipt.packaging.wizard', string='Wizard')
    product_id = fields.Many2one('product.product', string='Product', required=True)
    received_qty = fields.Float(string='Received Quantity', required=True)
    packaging_id = fields.Many2one('product.packaging', string='Packaging Type',
                                  domain="[('product_id', '=', product_id)]")
    move_line_id = fields.Many2one('stock.move.line', string='Move Line')
    
    # Vendor packaging fields
    is_vendor_packaged = fields.Boolean(string='Vendor Packaged')
    vendor_package_ref = fields.Char(string='Vendor Package Reference')
    package_count = fields.Integer(string='Package Count', default=1)
    
    # Repackaging information
    needs_repackaging = fields.Boolean(string='Needs Repackaging')
    repackaging_note = fields.Text(string='Repackaging Note')
    
    @api.onchange('packaging_id', 'received_qty')
    def _onchange_packaging_id(self):
        if self.packaging_id and self.packaging_id.qty > 0 and self.received_qty:
            # Calculate package count based on packaging quantity
            self.package_count = int(self.received_qty // self.packaging_id.qty)
            if self.received_qty % self.packaging_id.qty > 0:
                self.package_count += 1
    
    @api.onchange('package_count', 'received_qty')
    def _onchange_package_count(self):
        if self.package_count <= 0:
            self.package_count = 1