from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    # Package tracking fields
    package_count = fields.Integer(string="Package Count", compute='_compute_package_count')
    qty_packaged = fields.Float(string="Quantity Packaged", default=0.0)
    is_packaged = fields.Boolean(string="Is Packaged", default=False)
    can_create_packages = fields.Boolean(string="Can Create Packages", compute="_compute_can_create_packages")
    
    # Package statistics
    primary_package_count = fields.Integer(string="Primary Packages", compute='_compute_package_stats')
    secondary_package_count = fields.Integer(string="Secondary Packages", compute='_compute_package_stats')
    tertiary_package_count = fields.Integer(string="Tertiary Packages", compute='_compute_package_stats')
    
    # Packaging efficiency metrics
    packaging_efficiency = fields.Float(string="Packaging Efficiency %", compute='_compute_packaging_efficiency')
    
    def _compute_package_count(self):
        for production in self:
            production.package_count = self.env['stock.quant.package'].search_count([('mo_id', '=', production.id)])

    @api.depends('package_count')
    def _compute_package_stats(self):
        for production in self:
            packages = self.env['stock.quant.package'].search([('mo_id', '=', production.id)])
            production.primary_package_count = len(packages.filtered(lambda p: p.package_level == 'primary'))
            production.secondary_package_count = len(packages.filtered(lambda p: p.package_level == 'secondary'))
            production.tertiary_package_count = len(packages.filtered(lambda p: p.package_level == 'tertiary'))

    @api.depends('state', 'is_packaged')
    def _compute_can_create_packages(self):
        for production in self:
            production.can_create_packages = production.state == 'done' and not production.is_packaged

    @api.depends('qty_packaged', 'product_qty')
    def _compute_packaging_efficiency(self):
        for production in self:
            if production.product_qty:
                production.packaging_efficiency = (production.qty_packaged / production.product_qty) * 100
            else:
                production.packaging_efficiency = 0

    def create_packages(self, package_type_id, package_qty):
        self.ensure_one()
        if not self.can_create_packages:
            raise UserError(_('You can only create packages after the MO is done and not yet fully packaged.'))

        produced_qty = min(package_qty, self.product_qty - self.qty_packaged)
        if produced_qty <= 0:
            raise UserError(_('No quantity available for packaging.'))
            
        product = self.product_id

        packaging = self.env['product.packaging'].browse(package_type_id)
        if not packaging:
            raise UserError(_('No selected packaging type found.'))

        num_packages = int(produced_qty // packaging.qty)
        remainder_qty = produced_qty % packaging.qty

        created_packages = self.env['stock.quant.package']
        
        # Create full packages
        for _ in range(num_packages):
            # Get next sequence number
            sequence_obj = self.env['ir.sequence'].search([('code', '=', 'stock.package')], limit=1)
            next_number = sequence_obj._next() if sequence_obj else '00001'
            
            # Use packaging name as prefix
            package_name = f'{packaging.name}-{next_number}'
            package = self.env['stock.quant.package'].create({
                'name': package_name,
                'package_type_id': packaging.package_type_id.id,
                'mo_id': self.id,
                'packaging_date': fields.Datetime.now(),
            })
            created_packages |= package
            
            # Create quant for the package
            self.env['stock.quant'].create({
                'product_id': product.id,
                'quantity': packaging.qty,
                'package_id': package.id,
                'location_id': self.location_dest_id.id,
            })

        # Create remainder package if needed
        if remainder_qty > 0:
            # Get next sequence number
            sequence_obj = self.env['ir.sequence'].search([('code', '=', 'stock.package')], limit=1)
            next_number = sequence_obj._next() if sequence_obj else '00001'
            
            # Use packaging name as prefix
            package_name = f'{packaging.name}-{next_number}'
            package = self.env['stock.quant.package'].create({
                'name': package_name,
                'package_type_id': packaging.package_type_id.id,
                'mo_id': self.id,
                'packaging_date': fields.Datetime.now(),
            })
            created_packages |= package
            
            self.env['stock.quant'].create({
                'product_id': product.id,
                'quantity': remainder_qty,
                'package_id': package.id,
                'location_id': self.location_dest_id.id,
            })

        # Update packaged quantity
        self.qty_packaged += produced_qty

        if self.qty_packaged >= self.product_qty:
            self.write({'is_packaged': True})
            
        return created_packages

    def action_open_packaging_wizard(self):
        return {
            'name': _('Select Packaging Type'),
            'type': 'ir.actions.act_window',
            'res_model': 'packaging.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_production_id': self.id,
                'default_product_id': self.product_id.id,
                'default_available_qty': self.product_qty - self.qty_packaged,
            },
        }

    def action_create_secondary_packages(self):
        """Open wizard to create secondary packages (boxes of packages)"""
        return {
            'name': _('Create Secondary Packages'),
            'type': 'ir.actions.act_window',
            'res_model': 'secondary.packaging.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_production_id': self.id,
            },
        }

    def action_view_packages(self):
        self.ensure_one()
        return {
            'name': _('Packages'),
            'type': 'ir.actions.act_window',
            'view_mode': 'tree,form',
            'res_model': 'stock.quant.package',
            'domain': [('mo_id', '=', self.id)],
            'context': dict(self.env.context),
        }

    def copy(self, default=None):
        default = dict(default or {})
        default.update({
            'is_packaged': False,
            'qty_packaged': 0.0,
        })
        return super(MrpProduction, self).copy(default)