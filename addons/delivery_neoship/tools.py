import re

from . import const


def neoship_shipper_key(shipper_code):
    return (shipper_code or '').lower()


def neoship_code(value):
    return re.sub(const.REFERENCE_INVALID_CHARS, '-', value or '').strip('-')[: const.REFERENCE_MAX_LENGTH]


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
    suffix = f'-{sequence}'
    return reference[: const.REFERENCE_MAX_LENGTH - len(suffix)] + suffix
