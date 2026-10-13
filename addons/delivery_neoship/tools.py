import hashlib
import re

from . import const


def neoship_shipper_key(shipper_code):
    return (shipper_code or '').lower()


def neoship_clean(value):
    return re.sub(const.REFERENCE_INVALID_CHARS, '-', value or '').strip('-')


def neoship_code(value):
    return neoship_clean(value)[: const.REFERENCE_MAX_LENGTH]


def neoship_reference(prefix, name, delivery):
    suffix = f'{const.REFERENCE_DELIVERY_SEPARATOR}{delivery:0{const.REFERENCE_DELIVERY_DIGITS}d}'
    base = neoship_clean(f'{prefix}{name}')
    room = const.REFERENCE_MAX_LENGTH - const.REFERENCE_PACK_ROOM - len(suffix)
    if len(base) > room:
        # The fingerprint covers the cut-off start, so long names that end the same stay unique.
        head = f'{prefix}{neoship_fingerprint(base)}-'
        base = head + base[len(head) - room :].lstrip('-_')
    return base + suffix


def neoship_fingerprint(value):
    number = int(hashlib.sha256(value.encode()).hexdigest(), 16)
    alphabet = const.REFERENCE_FINGERPRINT_ALPHABET
    characters = []
    for _index in range(const.REFERENCE_FINGERPRINT_LENGTH):
        number, position = divmod(number, len(alphabet))
        characters.append(alphabet[position])
    return ''.join(characters)


def neoship_digits(value):
    return re.sub(r'\D', '', value or '')


def neoship_phone(value):
    return re.sub(r'\s+', '', value or '')


def neoship_same_phone(old, new):
    # Neoship may store the number with a country prefix it added, e.g. +48 for Polish Packeta carriers.
    return old == new or bool(old and new and (old.endswith(new) or new.endswith(old)))


def neoship_status_group(status):
    return status.group if status and status.group in const.STATUS_GROUPS else False


def neoship_combined_status_group(groups):
    active = [group for group in groups if group != const.STATUS_GROUP_CANCEL]
    if not active:
        return const.STATUS_GROUP_CANCEL
    if const.STATUS_GROUP_NOT_DELIVERED in active:
        return const.STATUS_GROUP_NOT_DELIVERED
    if not all(active):
        return False
    pending = [group for group in active if group not in const.STATUS_GROUPS_FINAL]
    if pending:
        return min(pending, key=const.STATUS_GROUPS.index)
    if const.STATUS_GROUP_RETURNED in active:
        return const.STATUS_GROUP_RETURNED
    return const.STATUS_GROUP_DELIVERED


def neoship_parcel_reference(reference, sequence):
    if sequence == 1:
        return reference
    return f'{reference}{const.REFERENCE_PACK_SEPARATOR}{sequence}'
