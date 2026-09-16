"""Single source of truth for supported activity types."""
import json
from pathlib import Path


with (Path(__file__).with_name('activity_definitions.json')).open(encoding='utf-8') as definitions_file:
    ACTIVITY_DEFINITIONS = json.load(definitions_file)

ACTIVITY_TYPES = tuple(ACTIVITY_DEFINITIONS)
ACTIVITY_LABELS = {key: value['label'] for key, value in ACTIVITY_DEFINITIONS.items()}
ACTIVITY_COLORS = {key: value['color'] for key, value in ACTIVITY_DEFINITIONS.items()}
ACTIVITY_UNITS = {key: value['unit'] for key, value in ACTIVITY_DEFINITIONS.items()}
ACTIVITY_SPECIFIC_DATA = {key: value.get('specific_data', {}) for key, value in ACTIVITY_DEFINITIONS.items()}


def activity_label(activity_type):
    return ACTIVITY_LABELS.get(activity_type, activity_type.replace('_', ' ').title())


def activity_value(activity, activity_type=None):
    activity_type = activity_type or getattr(activity, 'activity_type', None)
    if ACTIVITY_UNITS.get(activity_type) == 'min':
        return (getattr(activity, 'duration_seconds', 0) or 0) / 60.0
    return getattr(activity, 'distance_km', 0) or 0


def activity_specific_fields(activity_type):
    return ACTIVITY_SPECIFIC_DATA.get(activity_type, {})
