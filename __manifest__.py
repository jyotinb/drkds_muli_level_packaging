{
    'name': 'Advanced Auto Packaging System',
    'version': '17.0.1.0.0',
    'category': 'Inventory/Manufacturing',
    'summary': 'Complete packaging system for manufacturing, picking, and receiving',
    'description': """
Advanced Auto Packaging System
=============================
This module provides comprehensive packaging functionality across the entire supply chain:

Manufacturing:
- Create packages for manufactured products
- Select packaging types and quantities
- Track packaged vs. unpackaged quantities

Picking:
- Create packages during picking operations
- Support for multiple packaging types
- Package weight tracking
- Sequential package numbering

Receiving:
- Package items upon receipt
- Capture vendor packaging information
- Repackage into company-standard packaging

Key Features:
- Multi-level packaging hierarchy
- Detailed reporting on package content
- Package weight calculations
- Complete package traceability
- Support for multiple packaging types per product
    """,
    'author': 'drkds infotech',
    'website': 'https://www.drkdsinfo.com',
    'depends': [
        'stock',
        'mrp',
        'product',
        'purchase'
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'views/product_views.xml',
        'views/mrp_production_views.xml',
        'views/stock_picking_views.xml',
        'views/package_views.xml',
        'views/stock_move_views.xml',
        'views/stock_quant_views.xml',
        'views/purchase_views.xml',
        'wizards/packaging_wizard_views.xml',
        'wizards/picking_packaging_wizard_views.xml',
        'wizards/receipt_packaging_wizard_views.xml',
        'reports/package_report_views.xml',
        'reports/package_report_templates.xml',
    ],
    'demo': [],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}