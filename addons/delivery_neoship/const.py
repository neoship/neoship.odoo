DELIVERY_TYPE = 'neoship'

SHIPPER_CODE_GLS = 'gls'
SHIPPER_CODE_PACKETA = 'packeta'
SHIPPER_CODE_SPS = 'sps'
SHIPPER_CODE_DPD = 'dpd'
SHIPPER_CODE_SK_POSTA = 'sk_posta'
SHIPPER_CODE_SDS = 'sds'
SHIPPER_CODES_WITH_CARRIER_TYPE = (SHIPPER_CODE_PACKETA,)
# Neoship ignores count_of_packages for these carriers, so each pack is sent as its own shipment.
SHIPPER_CODES_SHIPMENT_PER_PACK = (SHIPPER_CODE_PACKETA,)
SHIPPER_DELIVERY_TYPE_PARCELSHOP = 'parcelshop'

# Carrier-specific formats from ../api, ../neoship-app and Neoship's API documentation.
# The API endpoint otherwise forces GLS's A4_2x2 for every shipper.
LABEL_PRINT_TYPES = {
    SHIPPER_CODE_GLS: 'A4_2x2',
    SHIPPER_CODE_PACKETA: 'A6 on A4',
    SHIPPER_CODE_SPS: 'a4',
    SHIPPER_CODE_DPD: 'A4',
    SHIPPER_CODE_SK_POSTA: 'A6',
    SHIPPER_CODE_SDS: 'default',
}

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
    'receiver_company',
    'receiver_email',
    'parcelshop',
    'cod_currency_code',
)
SHIPMENT_MATCH_PHONE_FIELDS = ('receiver_phone',)
COD_PRECISION_DIGITS = 2
WEIGHT_PRECISION_DIGITS = 3
COD_FIELDS = ('cod_price', 'cod_currency_code', 'cod_reference')

STATUS_GROUP_NEW = 'new'
STATUS_GROUP_EXPORTED = 'exported'
STATUS_GROUP_TRANSIT = 'transit'
STATUS_GROUP_DELIVERED = 'delivered'
STATUS_GROUP_NOT_DELIVERED = 'notdelivered'
STATUS_GROUP_RETURNED = 'returned'
STATUS_GROUP_CANCEL = 'cancel'
STATUS_GROUPS = (
    STATUS_GROUP_NEW,
    STATUS_GROUP_EXPORTED,
    STATUS_GROUP_TRANSIT,
    STATUS_GROUP_DELIVERED,
    STATUS_GROUP_NOT_DELIVERED,
    STATUS_GROUP_RETURNED,
    STATUS_GROUP_CANCEL,
)
STATUS_GROUPS_FINAL = (STATUS_GROUP_DELIVERED, STATUS_GROUP_RETURNED, STATUS_GROUP_CANCEL)

ENVIRONMENT_PRODUCTION = 'production'
ENVIRONMENT_TEST = 'test'

TRACKING_BATCH_SIZE = 100
TRACKING_LIMIT_PER_RUN = 500
TRACKING_DAYS_PARAM = 'delivery_neoship.tracking_days'
TRACKING_DAYS_DEFAULT = 30

CLOSURE_ACTIONS = {
    SHIPPER_CODE_SPS: 'daily_closing',
    SHIPPER_CODE_PACKETA: 'packeta_acceptance_protocol',
    SHIPPER_CODE_SK_POSTA: 'SK_POSTA_daily_closing',
}
CLOSURE_SHIPPERS_BY_DATE = (SHIPPER_CODE_PACKETA,)
CLOSURE_NO_PACKAGES = 'K dispozícii niesu žiadne balíky.'
CLOSURE_TIMEOUT = 120
CLOSURE_DEDUP_MINUTES = 10
CLOSURE_MAX_DAYS = 7
CLOSURE_DEFAULT_TIME = 15.0
CLOSURE_STATE_DONE = 'done'
CLOSURE_STATE_EMPTY = 'empty'
CLOSURE_STATE_FAILED = 'failed'
WEEKDAY_FIELDS = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')

OPTION_KIND_SHIPPER = 'shipper'
OPTION_KIND_CARRIER_TYPE = 'carrier_type'

ODOO_DELIVERY_TYPE_FIXED = 'fixed'
ODOO_PRODUCT_TYPE_SERVICE = 'service'
ODOO_INVOICE_POLICY_ORDER = 'order'
ODOO_UOM_KG = 'uom.product_uom_kgm'
ODOO_PICKING_STATE_CANCEL = 'cancel'
ODOO_CRON_INTERVAL_DAYS = 'days'
ODOO_SERVER_ACTION_CODE = 'code'
