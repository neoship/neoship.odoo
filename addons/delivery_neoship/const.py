DELIVERY_TYPE = 'neoship'

SHIPPER_CODE_PACKETA = 'packeta'
SHIPPER_CODES_WITH_CARRIER_TYPE = (SHIPPER_CODE_PACKETA,)

REFERENCE_MAX_LENGTH = 25
REFERENCE_COMPANY_PREFIX = 'C'
REFERENCE_INVALID_CHARS = r'[^A-Za-z0-9_-]+'
PACKETA_MAX_WEIGHT_KG = 15.0

SHIPMENT_MATCH_FIELDS = (
    'receiver_name',
    'receiver_street',
    'receiver_city',
    'receiver_zip',
    'receiver_state_code',
    'parcelshop',
    'cod_currency_code',
)
COD_PRECISION_DIGITS = 2

OPTION_KIND_SHIPPER = 'shipper'
OPTION_KIND_CARRIER_TYPE = 'carrier_type'

ODOO_DELIVERY_TYPE_FIXED = 'fixed'
ODOO_PRODUCT_TYPE_SERVICE = 'service'
ODOO_INVOICE_POLICY_ORDER = 'order'
ODOO_UOM_KG = 'uom.product_uom_kgm'
ODOO_PICKING_STATE_CANCEL = 'cancel'
