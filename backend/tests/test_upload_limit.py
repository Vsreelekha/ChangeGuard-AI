import asyncio

from app.core.upload_limit import ProjectUploadLimitMiddleware


def test_project_upload_middleware_limits_actual_request_bytes():
    sent = []
    incoming = [{"type": "http.request", "body": b"123456", "more_body": False}]

    async def receive():
        return incoming.pop(0)

    async def send(message):
        sent.append(message)

    async def app(scope, receive, send):
        await receive()
        await send({"type": "http.response.start", "status": 200, "headers": []})

    middleware = ProjectUploadLimitMiddleware(app, path="/api/v1/projects", max_request_bytes=5)
    scope = {"type": "http", "method": "POST", "path": "/api/v1/projects"}
    asyncio.run(middleware(scope, receive, send))

    assert sent[0]["status"] == 413


def test_project_upload_middleware_does_not_limit_other_endpoints():
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"123456", "more_body": False}

    async def send(message):
        sent.append(message)

    async def app(scope, receive, send):
        await receive()
        await send({"type": "http.response.start", "status": 200, "headers": []})

    middleware = ProjectUploadLimitMiddleware(app, path="/api/v1/projects", max_request_bytes=5)
    scope = {"type": "http", "method": "POST", "path": "/api/v1/analysis"}
    asyncio.run(middleware(scope, receive, send))

    assert sent[0]["status"] == 200


def test_project_upload_middleware_enforces_concurrent_request_limit():
    sent = []
    entered = asyncio.Event()
    release = asyncio.Event()

    async def receive():
        return {"type": "http.request", "body": b"x", "more_body": False}

    async def send(message):
        sent.append(message)

    async def app(scope, receive, send):
        await receive()
        entered.set()
        await release.wait()
        await send({"type": "http.response.start", "status": 200, "headers": []})

    middleware = ProjectUploadLimitMiddleware(
        app, path="/api/v1/projects", max_request_bytes=10, max_concurrent_uploads=1
    )
    scope = {"type": "http", "method": "POST", "path": "/api/v1/projects"}

    async def exercise():
        first = asyncio.create_task(middleware(scope, receive, send))
        await entered.wait()
        await middleware(scope, receive, send)
        release.set()
        await first

    asyncio.run(exercise())
    assert [message["status"] for message in sent if message["type"] == "http.response.start"] == [429, 200]
