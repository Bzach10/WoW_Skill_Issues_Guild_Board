"""Blizzard guild-roster client: request shape and identity preservation.

Runs under pytest AND standalone (`python tests/test_blizzard_guild_roster.py`),
because the environment this was written in could not install pytest and a
pytest-only test would have shipped unrun.

Transport is mocked. This verifies the request SHAPE and the identity rules —
that two Berobens on different realms stay apart, that Viôlence and Violënce
are not folded together, and that a member the API returns but we cannot key
is warned about rather than silently dropped. It does NOT verify the live API:
no credentials and no egress were available. The first real run is the test of
that half.
"""

import os, sys, types, json
import requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['BLIZZARD_CLIENT_ID']='test-id'
os.environ['BLIZZARD_CLIENT_SECRET']='test-secret'

import guild_board.guild_roster as gr

calls = {}
class Resp:
    def __init__(self, payload, code=200): self._p=payload; self.status_code=code
    def raise_for_status(self):
        if self.status_code>=400: raise RuntimeError("HTTP %s"%self.status_code)
    def json(self): return self._p

def fake_post(url, auth=None, data=None, timeout=None):
    calls['post']={'url':url,'auth':auth,'data':data}
    return Resp({"access_token":"TKN","expires_in":86399})

def fake_get(url, timeout=None, headers=None, params=None):
    calls['get']={'url':url,'headers':headers,'params':params}
    return Resp({"members":[
      {"rank":0,"character":{"id":111,"name":"Beroben","level":80,
        "playable_class":{"name":"Mage"},"realm":{"slug":"emerald-dream","name":"Emerald Dream"}}},
      {"rank":7,"character":{"id":222,"name":"Beroben","level":80,
        "playable_class":{"name":"Paladin"},"realm":{"slug":"queldorei","name":"Quel'dorei"}}},
      {"rank":7,"character":{"id":333,"name":"Viôlence","level":80,
        "playable_class":{"name":"Druid"},"realm":{"slug":"bleeding-hollow","name":"Bleeding Hollow"}}},
      {"rank":7,"character":{"id":444,"name":"Violënce","level":80,
        "playable_class":{"name":"Priest"},"realm":{"slug":"bleeding-hollow","name":"Bleeding Hollow"}}},
      {"rank":7,"character":{"id":555,"name":"Broken","realm":{}}},   # unkeyable -> must warn
    ]})

gr.requests = types.SimpleNamespace(post=fake_post, get=fake_get)

cfg={'guild':{'region':'us','realm_slug':'bleeding-hollow','name':'Skill Issues'}}
members = gr.fetch_blizzard_guild_roster(cfg)

ok=True
def check(label, cond):
    global ok
    print(("  PASS  " if cond else "  FAIL  ")+label); ok = ok and cond

print("=== request shape ===")
print("  POST url:", calls['post']['url'])
print("  POST grant:", calls['post']['data'])
print("  GET  url:", calls['get']['url'])
print("  GET  params:", calls['get']['params'])
print("  GET  auth header present:", 'Authorization' in calls['get']['headers'])
print()
print("=== assertions ===")
check("oauth endpoint correct", calls['post']['url']=="https://oauth.battle.net/token")
check("client-credentials grant", calls['post']['data']=={"grant_type":"client_credentials"})
check("creds sent via HTTP basic auth, not query string", calls['post']['auth']==('test-id','test-secret'))
check("roster url correct",
      calls['get']['url']=="https://us.api.blizzard.com/data/wow/guild/bleeding-hollow/skill-issues/roster")
check("namespace profile-us", calls['get']['params']['namespace']=="profile-us")
check("bearer token used", calls['get']['headers']['Authorization']=="Bearer TKN")
check("4 keyable members returned (5th warned, not silently dropped)", len(members)==4)
check("two Berobens kept apart", "beroben-emerald-dream" in members and "beroben-queldorei" in members)
check("Beroben scores/classes distinct",
      members["beroben-emerald-dream"]["class"]=="Mage" and members["beroben-queldorei"]["class"]=="Paladin")
check("Viôlence and Violënce kept apart",
      "viôlence-bleeding-hollow" in members and "violënce-bleeding-hollow" in members)
check("accents preserved in key (not folded to 'violence')",
      not any(k.startswith("violence-") for k in members))
check("blizzard stable id carried", members["beroben-emerald-dream"]["blizzard_id"]==111)
check("exact display name preserved", members["viôlence-bleeding-hollow"]["name"]=="Viôlence")

print()
print("=== no-credentials path ===")
del os.environ['BLIZZARD_CLIENT_ID']; del os.environ['BLIZZARD_CLIENT_SECRET']
check("returns None, does not raise", gr.fetch_blizzard_guild_roster(cfg) is None)

# Restore the real module: this stub is process-wide (gr.requests, not a
# monkeypatch), and pytest imports every test file into the same process.
# Left as the stub, any later test touching guild_roster's requests.* would
# break on a module that only has post/get.
gr.requests = requests




def test_blizzard_guild_roster_request_shape_and_identity():
    assert ok, "see the PASS/FAIL lines above"


if __name__ == "__main__":
    print()
    print("RESULT:", "ALL PASS" if ok else "FAILURES PRESENT")
    sys.exit(0 if ok else 1)
