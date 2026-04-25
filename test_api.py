import ccxt.async_support as ccxt
import asyncio

async def test():
    ex = ccxt.binanceusdm({'enableRateLimit': True})
    ex.set_sandbox_mode(True)
    print('Fetching markets...')
    try:
        markets = await ex.load_markets()
        print(f'Loaded {len(markets)} markets')
    except Exception as e:
        import traceback
        traceback.print_exc()
    finally:
        await ex.close()

asyncio.run(test())
