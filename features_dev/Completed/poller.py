import hashlib
import httpx
import asyncio
import json
from datetime import datetime, timezone

APP_KEY    = '8FB345B8693CCD00705B2242580910A0339A22A4105B6558'
APP_SECRET = '860d274a6c50445d86a93ed89de79278'
USER_ID    = 'Beacontelematics'
PASSWORD   = 'Transport01!'
BASE_URL   = 'https://eu-open.tracksolidpro.com/route/rest'

OUTPUT_FILE = 'api_output.txt'

def utc_now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

def build_sign(params):
    sorted_keys = sorted(params.keys())
    concat = ''.join(k + str(params[k]) for k in sorted_keys if params[k])
    return hashlib.md5((APP_SECRET + concat + APP_SECRET).encode('utf-8')).hexdigest().upper()

async def post(client, params):
    params['sign'] = build_sign(params)
    r = await client.post(BASE_URL, data=params)
    return r.json()

def log(msg, f):
    print(msg)
    f.write(msg + '\n')

async def main():
    with open(OUTPUT_FILE, 'w') as f:
        async with httpx.AsyncClient(timeout=15) as client:

            log('='*50, f)
            log('STEP 1: GET TOKEN', f)
            log('='*50, f)
            token_resp = await post(client, {
                'app_key':      APP_KEY,
                'expires_in':   '7200',
                'format':       'json',
                'method':       'jimi.oauth.token.get',
                'sign_method':  'md5',
                'timestamp':    utc_now(),
                'user_id':      USER_ID,
                'user_pwd_md5': hashlib.md5(PASSWORD.encode()).hexdigest().lower(),
                'v':            '0.9',
            })
            log(json.dumps(token_resp, indent=2), f)

            if token_resp.get('code') != 0:
                log('Token failed — stopping.', f)
                return
            token = token_resp['result']['accessToken']

            log('='*50, f)
            log('STEP 2: DEVICE LIST', f)
            log('='*50, f)
            dev_resp = await post(client, {
                'access_token': token,
                'app_key':      APP_KEY,
                'format':       'json',
                'method':       'jimi.user.device.list',
                'sign_method':  'md5',
                'timestamp':    utc_now(),
                'target':       USER_ID,
                'v':            '0.9',
            })
            log(json.dumps(dev_resp, indent=2), f)

            log('='*50, f)
            log('STEP 3: LOCATION + BATTERY', f)
            log('='*50, f)
            loc_resp = await post(client, {
                'access_token': token,
                'app_key':      APP_KEY,
                'format':       'json',
                'method':       'jimi.user.device.location.list',
                'sign_method':  'md5',
                'timestamp':    utc_now(),
                'target':       USER_ID,
                'v':            '0.9',
            })
            log(json.dumps(loc_resp, indent=2), f)

            # ── Summary ──
            devices  = dev_resp.get('result', [])
            locations = loc_resp.get('result', [])
            pos_types = {}
            for d in locations:
                pt = d.get('posType', 'unknown')
                pos_types[pt] = pos_types.get(pt, 0) + 1

            log('='*50, f)
            log('SUMMARY', f)
            log('='*50, f)
            log(f'Device list count:   {len(devices)}', f)
            log(f'Location list count: {len(locations)}', f)
            log(f'posType breakdown:   {pos_types}', f)
            log(f'Battery populated:   {sum(1 for d in locations if d.get("electQuantity"))}/{len(locations)}', f)
            log(f'locDesc populated:   {sum(1 for d in locations if d.get("locDesc"))}/{len(locations)}', f)
            log(f'Online devices:      {sum(1 for d in locations if d.get("status")=="1")}/{len(locations)}', f)
            log(f'Output saved to:     {OUTPUT_FILE}', f)

asyncio.run(main())