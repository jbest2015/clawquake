"""
Quake 3 protocol constants and field definitions.

These define the wire format for parsing game state snapshots,
player states, and entity states from the Q3 network protocol.
"""

import collections
import enum

# --- Protocol constants ---
GENTITYNUM_BITS = 10
FLOAT_INT_BITS = 13
FLOAT_INT_BIAS = 1 << (FLOAT_INT_BITS - 1)
MAX_GENTITIES = 1 << GENTITYNUM_BITS
MAX_CLIENTS = 64
MAX_PACKETLEN = 1400
FRAGMENT_SIZE = MAX_PACKETLEN - 100
FRAGMENT_BIT = 1 << 31
MAX_RELIABLE_COMMANDS = 64
PACKET_BACKUP = 32
PACKET_MASK = PACKET_BACKUP - 1
MAX_CONFIGSTRINGS = 1024
MAX_MSGLEN = 16384

# Connection sequence marker: Q3 uses 0xFFFFFFFF for connectionless packets
CONNECTIONLESS_MARKER = 0xFFFFFFFF


# --- Server operations ---
class svc_ops_e(enum.IntEnum):
    svc_bad = 0
    svc_nop = 1
    svc_gamestate = 2
    svc_configstring = 3
    svc_baseline = 4
    svc_serverCommand = 5
    svc_download = 6
    svc_snapshot = 7
    svc_EOF = 8


# --- Client operations ---
class clc_ops_e(enum.IntEnum):
    clc_bad = 0
    clc_nop = 1
    clc_move = 2
    clc_moveNoDelta = 3
    clc_clientCommand = 4
    clc_EOF = 5


# --- Connection states ---
class connstate_t(enum.Enum):
    CA_DISCONNECTED = 0
    CA_CONNECTING = 1
    CA_CHALLENGING = 2
    CA_CONNECTED = 3
    CA_PRIMED = 4
    CA_ACTIVE = 5


# --- Config string indices ---
class configstr_t(enum.IntEnum):
    CS_SERVERINFO = 0
    CS_SYSTEMINFO = 1
    CS_MUSIC = 2
    CS_MESSAGE = 3
    CS_MOTD = 4
    CS_WARMUP = 5
    CS_SCORES1 = 6
    CS_SCORES2 = 7
    CS_VOTE_TIME = 8
    CS_VOTE_STRING = 9
    CS_VOTE_YES = 10
    CS_VOTE_NO = 11
    CS_GAME_VERSION = 12
    CS_LEVEL_START_TIME = 13
    CS_INTERMISSION = 14
    CS_ITEMS = 27
    CS_MODELS = 32
    CS_SOUNDS_START = 288  # CS_MODELS + MAX_MODELS(256)
    CS_PLAYERS = 544       # CS_SOUNDS + MAX_SOUNDS(256)
    CS_LOCATIONS = 608     # CS_PLAYERS + MAX_CLIENTS(64)


# --- Entity types ---
class entityType_t(enum.IntEnum):
    ET_GENERAL = 0
    ET_PLAYER = 1
    ET_ITEM = 2
    ET_MISSILE = 3
    ET_MOVER = 4
    ET_BEAM = 5
    ET_PORTAL = 6
    ET_SPEAKER = 7
    ET_PUSH_TRIGGER = 8
    ET_TELEPORT_TRIGGER = 9
    ET_INVISIBLE = 10
    ET_GRAPPLE = 11
    ET_TEAM = 12
    ET_EVENTS = 13


# --- Weapons ---
class weapon_t(enum.IntEnum):
    WP_NONE = 0
    WP_GAUNTLET = 1
    WP_MACHINEGUN = 2
    WP_SHOTGUN = 3
    WP_GRENADE_LAUNCHER = 4
    WP_ROCKET_LAUNCHER = 5
    WP_LIGHTNING = 6
    WP_RAILGUN = 7
    WP_PLASMAGUN = 8
    WP_BFG = 9
    WP_GRAPPLING_HOOK = 10
    WP_NUM_WEAPONS = 11


# --- Means of death (for kill messages) ---
class meansOfDeath_t(enum.IntEnum):
    MOD_UNKNOWN = 0
    MOD_SHOTGUN = 1
    MOD_GAUNTLET = 2
    MOD_MACHINEGUN = 3
    MOD_GRENADE = 4
    MOD_GRENADE_SPLASH = 5
    MOD_ROCKET = 6
    MOD_ROCKET_SPLASH = 7
    MOD_PLASMA = 8
    MOD_PLASMA_SPLASH = 9
    MOD_RAILGUN = 10
    MOD_LIGHTNING = 11
    MOD_BFG = 12
    MOD_BFG_SPLASH = 13
    MOD_WATER = 14
    MOD_SLIME = 15
    MOD_LAVA = 16
    MOD_CRUSH = 17
    MOD_TELEFRAG = 18
    MOD_FALLING = 19
    MOD_SUICIDE = 20
    MOD_TARGET_LASER = 21
    MOD_TRIGGER_HURT = 22
    MOD_GRAPPLE = 23


# --- Field definitions for delta-compressed state ---
FieldDefinition = collections.namedtuple("FieldDefinition", ["name", "bits"])

PLAYERSTATE_FIELDS = [
    FieldDefinition("commandTime", 32),
    FieldDefinition("origin[0]", 0),
    FieldDefinition("origin[1]", 0),
    FieldDefinition("bobCycle", 8),
    FieldDefinition("velocity[0]", 0),
    FieldDefinition("velocity[1]", 0),
    FieldDefinition("viewangles[1]", 0),
    FieldDefinition("viewangles[0]", 0),
    FieldDefinition("weaponTime", -16),
    FieldDefinition("origin[2]", 0),
    FieldDefinition("velocity[2]", 0),
    FieldDefinition("legsTimer", 8),
    FieldDefinition("pm_time", -16),
    FieldDefinition("eventSequence", 16),
    FieldDefinition("torsoAnim", 8),
    FieldDefinition("movementDir", 4),
    FieldDefinition("events[0]", 8),
    FieldDefinition("legsAnim", 8),
    FieldDefinition("events[1]", 8),
    FieldDefinition("pm_flags", 16),
    FieldDefinition("groundEntityNum", GENTITYNUM_BITS),
    FieldDefinition("weaponstate", 4),
    FieldDefinition("eFlags", 16),
    FieldDefinition("externalEvent", 10),
    FieldDefinition("gravity", 16),
    FieldDefinition("speed", 16),
    FieldDefinition("delta_angles[1]", 16),
    FieldDefinition("externalEventParm", 8),
    FieldDefinition("viewheight", -8),
    FieldDefinition("damageEvent", 8),
    FieldDefinition("damageYaw", 8),
    FieldDefinition("damagePitch", 8),
    FieldDefinition("damageCount", 8),
    FieldDefinition("generic1", 8),
    FieldDefinition("pm_type", 8),
    FieldDefinition("delta_angles[0]", 16),
    FieldDefinition("delta_angles[2]", 16),
    FieldDefinition("torsoTimer", 12),
    FieldDefinition("eventParms[0]", 8),
    FieldDefinition("eventParms[1]", 8),
    FieldDefinition("clientNum", 8),
    FieldDefinition("weapon", 5),
    FieldDefinition("viewangles[2]", 0),
    FieldDefinition("grapplePoint[0]", 0),
    FieldDefinition("grapplePoint[1]", 0),
    FieldDefinition("grapplePoint[2]", 0),
    FieldDefinition("jumppad_ent", 10),
    FieldDefinition("loopSound", 16),
]

ENTITY_FIELDS = [
    FieldDefinition("pos.trTime", 32),
    FieldDefinition("pos.trBase[0]", 0),
    FieldDefinition("pos.trBase[1]", 0),
    FieldDefinition("pos.trDelta[0]", 0),
    FieldDefinition("pos.trDelta[1]", 0),
    FieldDefinition("pos.trBase[2]", 0),
    FieldDefinition("apos.trBase[1]", 0),
    FieldDefinition("pos.trDelta[2]", 0),
    FieldDefinition("apos.trBase[0]", 0),
    FieldDefinition("event", 10),
    FieldDefinition("angles2[1]", 0),
    FieldDefinition("eType", 8),
    FieldDefinition("torsoAnim", 8),
    FieldDefinition("eventParm", 8),
    FieldDefinition("legsAnim", 8),
    FieldDefinition("groundEntityNum", GENTITYNUM_BITS),
    FieldDefinition("pos.trType", 8),
    FieldDefinition("eFlags", 19),
    FieldDefinition("otherEntityNum", GENTITYNUM_BITS),
    FieldDefinition("weapon", 8),
    FieldDefinition("clientNum", 8),
    FieldDefinition("angles[1]", 0),
    FieldDefinition("pos.trDuration", 32),
    FieldDefinition("apos.trType", 8),
    FieldDefinition("origin[0]", 0),
    FieldDefinition("origin[1]", 0),
    FieldDefinition("origin[2]", 0),
    FieldDefinition("solid", 24),
    FieldDefinition("powerups", 16),
    FieldDefinition("modelindex", 8),
    FieldDefinition("otherEntityNum2", GENTITYNUM_BITS),
    FieldDefinition("loopSound", 8),
    FieldDefinition("generic1", 8),
    FieldDefinition("origin2[2]", 0),
    FieldDefinition("origin2[0]", 0),
    FieldDefinition("origin2[1]", 0),
    FieldDefinition("modelindex2", 8),
    FieldDefinition("angles[0]", 0),
    FieldDefinition("time", 32),
    FieldDefinition("apos.trTime", 32),
    FieldDefinition("apos.trDuration", 32),
    FieldDefinition("apos.trBase[2]", 0),
    FieldDefinition("apos.trDelta[0]", 0),
    FieldDefinition("apos.trDelta[1]", 0),
    FieldDefinition("apos.trDelta[2]", 0),
    FieldDefinition("time2", 32),
    FieldDefinition("angles[2]", 0),
    FieldDefinition("angles2[0]", 0),
    FieldDefinition("angles2[2]", 0),
    FieldDefinition("constantLight", 32),
    FieldDefinition("frame", 16),
]
