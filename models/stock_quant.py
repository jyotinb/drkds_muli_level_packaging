from odoo import models, fields, api, _

class StockQuant(models.Model):
    _inherit = 'stock.quant'

    # Enhanced packaging fields for quants
    packaged_qty = fields.Float(string='Packaged Quantity', compute='_compute_packaged_qty')
    unpackaged_qty = fields.Float(string='Unpackaged Quantity', compute='_compute_packaged_qty')
    packaging_state = fields.Selection([
        ('unpackaged', 'Unpackaged'),
        ('partial', 'Partially Packaged'),
        ('packaged', 'Fully Packaged')
    ], string='Packaging State', compute='_compute_packaged_qty')
    
    @api.depends('quantity', 'package_id')
    def _compute_packaged_qty(self):
        """Compute how much of the quant is packaged vs unpackaged"""
        for quant in self:
            if quant.package_id:
                quant.packaged_qty = quant.quantity
                quant.unpackaged_qty = 0.0
                quant.packaging_state = 'packaged'
            else:
                quant.packaged_qty = 0.0
                quant.unpackaged_qty = quant.quantity
                quant.packaging_state = 'unpackaged'
                
                # Check if there are other quants for same product/location that are packaged
                packaged_quants = self.env['stock.quant'].search([
                    ('product_id', '=', quant.product_id.id),
                    ('location_id', '=', quant.location_id.id),
                    ('package_id', '!=', False)
                ])
                if packaged_quants:
                    quant.packaging_state = 'partial'
    
    def action_package_remaining(self):
        """Package remaining quantities into new packages"""
        for quant in self:
            if quant.unpackaged_qty <= 0 or quant.package_id:
                continue
                
            # Check if the product has packaging defined
            if not quant.product_id.packaging_ids:
                continue
                
            # Get default packaging
            packaging = quant.product_id.packaging_ids[0]
            
            # Calculate needed packages
            qty_to_package = quant.unpackaged_qty
            package_qty = packaging.qty
            
            num_packages = int(qty_to_package // package_qty)
            remainder_qty = qty_to_package % package_qty
            
            # Create packages
            for i in range(num_packages):
                # Generate package name
                sequence_obj = self.env['ir.sequence'].search([('code', '=', 'stock.package')], limit=1)
                next_number = sequence_obj._next() if sequence_obj else f"{i+1:05d}"
                package_name = f"{packaging.name}-{next_number}"
                
                # Create package
                package = self.env['stock.quant.package'].create({
                    'name': package_name,
                    'package_type_id': packaging.package_type_id.id,
                    'packaging_date': fields.Datetime.now(),
                })
                
                # Create new quant for the package
                self.env['stock.quant'].create({
                    'product_id': quant.product_id.id,
                    'quantity': package_qty,
                    'location_id': quant.location_id.id,
                    'package_id': package.id,
                })
                
                # Reduce quantity from original quant
                quant.quantity -= package_qty
                
            # Handle remainder
            if remainder_qty > 0:
                # Either create a new package or leave as unpackaged based on remainder size
                if remainder_qty >= (package_qty * 0.5):  # If remainder is at least half a package
                    # Generate package name
                    sequence_obj = self.env['ir.sequence'].search([('code', '=', 'stock.package')], limit=1)
                    next_number = sequence_obj._next() if sequence_obj else f"{num_packages+1:05d}"
                    package_name = f"{packaging.name}-{next_number}"
                    
                    # Create package
                    package = self.env['stock.quant.package'].create({
                        'name': package_name,
                        'package_type_id': packaging.package_type_id.id,
                        'packaging_date': fields.Datetime.now(),
                    })
                    
                    # Create new quant for the package
                    self.env['stock.quant'].create({
                        'product_id': quant.product_id.id,
                        'quantity': remainder_qty,
                        'location_id': quant.location_id.id,
                        'package_id': package.id,
                    })
                    
                    # Reduce quantity from original quant
                    quant.quantity -= remainder_qty