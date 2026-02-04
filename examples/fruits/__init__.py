# http://localhost:8000/fruits

FRUITS = [b'<a href="/fruits/apple">Apple</a>', b'Banana']


async def get(request, response, **server):
    yield b'<h2>Fruits</h2><form action="/fruits" method="post"><ul>'

    for fruit in FRUITS:
        yield b'<li>%s</li>' % fruit

    yield (
        b'<li><input type="text" name="fruit" placeholder="Orange" /></li>'
        b'<li><input type="text" name="fruit" /></li>'
        b'<li><input type="submit" value="Add" /></li>'
        b'</ul></form>'
    )


async def post(request, response, **server):
    form_data = await request.form()

    if 'fruit' in form_data:
        for fruit in form_data['fruit']:
            FRUITS.append(fruit.encode())

            if len(FRUITS) > 5:
                del FRUITS[0]

    raise response.redirect('/fruits')
