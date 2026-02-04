# http://localhost:8000/fruits/apple

async def get(request, response, **server):
    return (
        '<h2>Apple</h2>'
        '<p>An apple is the round, edible <a href="/fruits">fruit</a> of an '
        'apple tree (<i>Malus spp.</i>).</p>'
    )
