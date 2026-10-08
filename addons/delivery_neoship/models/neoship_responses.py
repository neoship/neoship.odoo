from dataclasses import dataclass


def _float(value):
    return float(value) if value is not None else None


@dataclass(frozen=True)
class Shipper:
    id: int
    name: str
    shortcut: str
    delivery_types: tuple[str, ...] = ()

    @classmethod
    def from_json(cls, data):
        return cls(
            id=int(data['id']),
            name=data['name'],
            shortcut=data['shortcut'],
            delivery_types=tuple(delivery_type['type'] for delivery_type in data.get('delivery_types') or ()),
        )


@dataclass(frozen=True)
class PacketaCarrier:
    packeta_id: int
    name: str
    state_code: str
    currency: str | None

    @classmethod
    def from_json(cls, data):
        return cls(int(data['packeta_id']), data['name'], data['state_code'], data.get('currency'))


@dataclass(frozen=True)
class Status:
    id: int
    name: str | None
    group: str | None

    @classmethod
    def from_json(cls, data):
        return cls(int(data['id']), data.get('name'), data.get('group'))


@dataclass(frozen=True)
class Shipment:
    id: int
    reference_number: str | None = None
    tracking_number: str | None = None
    shipper: Shipper | None = None
    last_status: Status | None = None
    sub_packages: tuple['Shipment', ...] = ()
    errors: tuple[str, ...] = ()
    receiver_name: str | None = None
    receiver_company: str | None = None
    receiver_street: str | None = None
    receiver_city: str | None = None
    receiver_zip: str | None = None
    receiver_state_code: str | None = None
    receiver_email: str | None = None
    receiver_phone: str | None = None
    parcelshop: str | None = None
    cod_price: float | None = None
    cod_currency_code: str | None = None
    weight: float | None = None

    @classmethod
    def from_json(cls, data):
        return cls(
            id=int(data['id']),
            reference_number=data.get('reference_number'),
            tracking_number=data.get('tracking_number'),
            shipper=Shipper.from_json(data['shipper']) if data.get('shipper') else None,
            last_status=Status.from_json(data['last_status']) if data.get('last_status') else None,
            sub_packages=tuple(map(cls.from_json, data.get('packages') or ())),
            errors=tuple(map(str, data.get('errors') or ())),
            receiver_name=data.get('receiver_name'),
            receiver_company=data.get('receiver_company'),
            receiver_street=data.get('receiver_street'),
            receiver_city=data.get('receiver_city'),
            receiver_zip=data.get('receiver_zip'),
            receiver_state_code=data.get('receiver_state_code'),
            receiver_email=data.get('receiver_email'),
            receiver_phone=data.get('receiver_phone'),
            parcelshop=data.get('parcelshop'),
            cod_price=_float(data.get('cod_price')),
            cod_currency_code=data.get('cod_currency_code'),
            weight=_float(data.get('weight')),
        )


@dataclass(frozen=True)
class ClosureResult:
    errors: str
    package_ids: tuple
    protocol: str

    @classmethod
    def from_json(cls, data):
        errors = data.get('errors') or ''
        return cls(
            errors='; '.join(map(str, errors)) if isinstance(errors, list) else str(errors),
            package_ids=tuple(data.get('package_ids') or ()),
            protocol=data.get('protocol') or '',
        )
