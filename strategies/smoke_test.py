"""
Simple test strategy to verify architecture.
"""
STRATEGY_NAME = "Test Strategy v2"
STRATEGY_VERSION = "2.0"

def on_spawn(ctx):
    ctx.start_time = 0

async def tick(bot, game, ctx):
    # Simply spin and attack
    actions = ["attack", "turn_left 15"]
    
    # Simple state check
    if game.my_health < 50:
        actions.append("say Ouch!")
        
    return actions
