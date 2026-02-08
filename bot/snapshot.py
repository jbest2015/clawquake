"""
Quake 3 snapshot parser - reads delta-compressed game state from server frames.

Parses player states (your own state) and entity states (other players, items,
projectiles, etc.) from Q3 server snapshot packets.

Based on the quake3-proxy-aimbot reference implementation by jfedor2.
"""

import logging

from .defs import (
    PLAYERSTATE_FIELDS, ENTITY_FIELDS, FLOAT_INT_BITS, FLOAT_INT_BIAS,
    GENTITYNUM_BITS, MAX_GENTITIES, svc_ops_e, entityType_t,
)

logger = logging.getLogger('clawquake.snapshot')


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
        # Q3 stores health in stats[STAT_HEALTH] (index 0)
        if self.stats and len(self.stats) > 0:
            return self.stats[0]
        return self.fields.get('generic1', 0)

    @property
    def armor(self):
        # Q3 stores armor in stats[STAT_ARMOR] (index 6)
        if self.stats and len(self.stats) > 6:
            return self.stats[6]
        return 0

    @property
    def weapon(self):
        return self.fields.get('weapon', 0)

    @property
    def client_num(self):
        return self.fields.get('clientNum', 0)

    # Stats arrays (populated from arrays section)
    stats = None
    persistant = None
    ammo = None
    powerups = None

    def copy(self):
        ps = PlayerState()
        ps.fields = dict(self.fields)
        ps.stats = list(self.stats) if self.stats else None
        ps.persistant = list(self.persistant) if self.persistant else None
        ps.ammo = list(self.ammo) if self.ammo else None
        ps.powerups = list(self.powerups) if self.powerups else None
        return ps


class EntityState:
    """Represents an entity's state from a server snapshot."""

    def __init__(self, number=0):
        self.number = number
        self.fields = {}

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
    """Read a delta-compressed player state from the buffer.

    Format (per quake3-proxy-aimbot reference):
      field_count: 8 bits
      For each field (0..field_count-1):
        field_changed: 1 bit
        If changed:
          If float field (bits==0):
            int_or_float: 1 bit
              0: read_int_float (13 bits with bias)
              1: read_float (32 bits IEEE)
          Else integer field:
            read_bits(field.bits)
      arrays_changed: 1 bit
      If arrays changed:
        stats, persistant, ammo, powerups arrays
    """
    ps = old_ps.copy() if old_ps else PlayerState()
    field_count = len(PLAYERSTATE_FIELDS)

    last_field = buf.read_byte()

    if last_field > field_count:
        logger.warning(f"Playerstate field_count={last_field} > max={field_count}, clamping")
        last_field = field_count

    for i in range(last_field):
        if not buf.read_bit():
            continue  # field not changed

        field = PLAYERSTATE_FIELDS[i]

        if field.bits == 0:
            # Float field
            if buf.read_bit():
                # Full IEEE float
                val = buf.read_float()
            else:
                # Int-encoded float (13 bits with bias)
                val = buf.read_int_float()
            ps.fields[field.name] = val
        else:
            # Integer field
            bits = abs(field.bits)
            val = buf.read_bits(bits)
            ps.fields[field.name] = val

    # Read arrays section
    if buf.read_bit():  # arrays_changed
        # Stats array (16 entries, each 16 bits)
        if buf.read_bit():  # stats_changed
            bits = buf.read_bits(16)
            if ps.stats is None:
                ps.stats = [0] * 16
            for i in range(16):
                if bits & (1 << i):
                    ps.stats[i] = buf.read_bits(16)

        # Persistant array (16 entries, each 16 bits)
        if buf.read_bit():  # persistant_changed
            bits = buf.read_bits(16)
            if ps.persistant is None:
                ps.persistant = [0] * 16
            for i in range(16):
                if bits & (1 << i):
                    ps.persistant[i] = buf.read_bits(16)

        # Ammo array (16 entries, each 16 bits)
        if buf.read_bit():  # ammo_changed
            bits = buf.read_bits(16)
            if ps.ammo is None:
                ps.ammo = [0] * 16
            for i in range(16):
                if bits & (1 << i):
                    ps.ammo[i] = buf.read_bits(16)

        # Powerups array (16 entries, each 32 bits)
        if buf.read_bit():  # powerups_changed
            bits = buf.read_bits(16)
            if ps.powerups is None:
                ps.powerups = [0] * 16
            for i in range(16):
                if bits & (1 << i):
                    ps.powerups[i] = buf.read_bits(32)

    return ps


def read_delta_entity(buf, old_es, number, key=None):
    """Read a delta-compressed entity state from the buffer.

    Format (per quake3-proxy-aimbot reference):
      entity_changed: 1 bit (called after remove check in caller)
      If changed:
        field_count: 8 bits
        For each field (0..field_count-1):
          field_changed: 1 bit
          If changed:
            If float field (bits==0):
              float_is_not_zero: 1 bit
              If not zero:
                int_or_float: 1 bit
                  0: read_int_float
                  1: read_float
              Else: value = 0
            Else integer field:
              int_is_not_zero: 1 bit
              If not zero: read_bits(field.bits)
              Else: value = 0
    """
    es = old_es.copy() if old_es else EntityState(number)
    es.number = number

    # Check if entity has changes
    if not buf.read_bit():  # entity_changed
        # No changes, return as-is
        return es

    field_count = len(ENTITY_FIELDS)
    last_field = buf.read_byte()

    if last_field > field_count:
        logger.warning(f"Entity last_field={last_field} > field_count={field_count}, clamping")
        last_field = field_count

    for i in range(last_field):
        if not buf.read_bit():
            continue  # field not changed

        field = ENTITY_FIELDS[i]

        if field.bits == 0:
            # Float field: extra "is not zero" bit
            if buf.read_bit():  # float_is_not_zero
                if buf.read_bit():  # int_or_float
                    es.fields[field.name] = buf.read_float()
                else:
                    es.fields[field.name] = buf.read_int_float()
            else:
                es.fields[field.name] = 0
        else:
            # Integer field: extra "is not zero" bit
            if buf.read_bit():  # int_is_not_zero
                es.fields[field.name] = buf.read_bits(field.bits)
            else:
                es.fields[field.name] = 0

    return es
