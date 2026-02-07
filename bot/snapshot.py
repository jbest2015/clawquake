"""
Quake 3 snapshot parser - reads delta-compressed game state from server frames.

Parses player states (your own state) and entity states (other players, items,
projectiles, etc.) from Q3 server snapshot packets.
"""

from .defs import (
    PLAYERSTATE_FIELDS, ENTITY_FIELDS, FLOAT_INT_BITS, FLOAT_INT_BIAS,
    GENTITYNUM_BITS, MAX_GENTITIES, svc_ops_e, entityType_t,
)


class PlayerState:
    """Represents the local player's state from a server snapshot."""

    def __init__(self):
        self.fields = {}
        for field in PLAYERSTATE_FIELDS:
            self.fields[field.name] = 0

    def __getattr__(self, name):
        if name != 'fields' and name in self.__dict__.get('fields', {}):
            return self.fields[name]
        raise AttributeError(f"PlayerState has no field '{name}'")

    @property
    def origin(self):
        return (self.fields.get('origin[0]', 0),
                self.fields.get('origin[1]', 0),
                self.fields.get('origin[2]', 0))

    @property
    def velocity(self):
        return (self.fields.get('velocity[0]', 0),
                self.fields.get('velocity[1]', 0),
                self.fields.get('velocity[2]', 0))

    @property
    def viewangles(self):
        return (self.fields.get('viewangles[0]', 0),
                self.fields.get('viewangles[1]', 0),
                self.fields.get('viewangles[2]', 0))

    @property
    def health(self):
        # Health is in stats, but also derivable from events
        return self.fields.get('generic1', 0)

    @property
    def weapon(self):
        return self.fields.get('weapon', 0)

    @property
    def client_num(self):
        return self.fields.get('clientNum', 0)

    def copy(self):
        ps = PlayerState()
        ps.fields = dict(self.fields)
        return ps


class EntityState:
    """Represents an entity's state from a server snapshot."""

    def __init__(self, number=0):
        self.number = number
        self.fields = {}
        for field in ENTITY_FIELDS:
            self.fields[field.name] = 0

    @property
    def origin(self):
        return (self.fields.get('pos.trBase[0]', 0),
                self.fields.get('pos.trBase[1]', 0),
                self.fields.get('pos.trBase[2]', 0))

    @property
    def entity_type(self):
        return self.fields.get('eType', 0)

    @property
    def is_player(self):
        return self.entity_type == entityType_t.ET_PLAYER

    @property
    def client_num(self):
        return self.fields.get('clientNum', 0)

    @property
    def weapon(self):
        return self.fields.get('weapon', 0)

    def copy(self):
        es = EntityState(self.number)
        es.fields = dict(self.fields)
        return es


class Snapshot:
    """A complete server snapshot: player state + all entity states."""

    def __init__(self):
        self.server_time = 0
        self.message_num = 0
        self.player_state = PlayerState()
        self.entities = {}  # entity number -> EntityState

    def get_players(self):
        """Get all player entities from the snapshot."""
        return {num: ent for num, ent in self.entities.items() if ent.is_player}


def read_delta_playerstate(buf, old_ps):
    """Read a delta-compressed player state from the buffer."""
    ps = old_ps.copy() if old_ps else PlayerState()

    # Read field mask
    field_count = len(PLAYERSTATE_FIELDS)
    last_field = buf.read_byte()

    for i in range(last_field):
        if not buf.read_bit():
            continue  # field not changed

        field = PLAYERSTATE_FIELDS[i]

        if field.bits == 0:
            # Float field - could be int-encoded or full float
            if buf.read_bit():
                # Full float
                ps.fields[field.name] = buf.read_float()
            else:
                # Int-encoded float
                ps.fields[field.name] = buf.read_int_float()
        else:
            # Integer field
            ps.fields[field.name] = buf.read_bits(field.bits)

    return ps


def read_delta_entity(buf, old_es, number, key=None):
    """Read a delta-compressed entity state from the buffer."""
    es = old_es.copy() if old_es else EntityState(number)
    es.number = number

    # Check for removal
    if buf.read_bit():
        # Entity removed
        return None

    # Check if there are changes
    if not buf.read_bit():
        # No changes
        return es

    field_count = len(ENTITY_FIELDS)
    last_field = buf.read_byte()

    for i in range(last_field):
        if not buf.read_bit():
            continue  # field not changed

        field = ENTITY_FIELDS[i]

        if field.bits == 0:
            # Float field
            if buf.read_bit():
                ps_val = buf.read_float()
            else:
                ps_val = buf.read_int_float()
            es.fields[field.name] = ps_val
        else:
            es.fields[field.name] = buf.read_bits(field.bits)

    return es
