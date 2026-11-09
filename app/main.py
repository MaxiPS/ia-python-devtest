from contextlib import asynccontextmanager
from typing import cast

import httpx
from fastapi import FastAPI, HTTPException, Request, Response, status

from app.clients.provider import ProviderClient, ProviderGateway
from app.models import CreateRequest, RequestCreated, RequestStatusResponse
from app.processing import ProcessingService
from app.request_store import RequestStore
from app.settings import Settings


def create_app(
    provider_gateway: ProviderGateway | None = None,
    request_store: RequestStore | None = None,
    settings: Settings | None = None,
    http_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    configured_settings = settings or Settings.from_env()
    store = request_store or RequestStore()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        http_client: httpx.AsyncClient | None = None
        gateway = provider_gateway

        if gateway is None:
            http_client = httpx.AsyncClient(
                base_url=configured_settings.provider_base_url,
                headers={
                    "X-API-Key": configured_settings.provider_api_key,
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(8.0, connect=2.0, pool=15.0),
                limits=httpx.Limits(
                    max_connections=100,
                    max_keepalive_connections=20,
                ),
                transport=http_transport,
            )
            gateway = ProviderClient(http_client)

        application.state.request_store = store
        application.state.processing_service = ProcessingService(store, gateway)

        try:
            yield
        finally:
            if http_client is not None:
                await http_client.aclose()

    application = FastAPI(
        title="Notification Service (Technical Test)",
        lifespan=lifespan,
    )

    @application.post(
        "/v1/requests",
        response_model=RequestCreated,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_request(
        payload: CreateRequest, request: Request
    ) -> RequestCreated:
        request_store = cast(RequestStore, request.app.state.request_store)
        record = request_store.create(payload.user_input)
        return RequestCreated(id=record.id)

    @application.post(
        "/v1/requests/{request_id}/process",
        response_model=RequestStatusResponse,
    )
    async def process_request(
        request_id: str,
        request: Request,
        response: Response,
    ) -> RequestStatusResponse:
        service = cast(ProcessingService, request.app.state.processing_service)
        record = await service.process_request(request_id)
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Request not found",
            )

        if record.status == "processing":
            response.status_code = status.HTTP_202_ACCEPTED

        return RequestStatusResponse(id=record.id, status=record.status)

    @application.get(
        "/v1/requests/{request_id}",
        response_model=RequestStatusResponse,
    )
    async def get_request_status(
        request_id: str,
        request: Request,
    ) -> RequestStatusResponse:
        request_store = cast(RequestStore, request.app.state.request_store)
        record = request_store.get(request_id)
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Request not found",
            )

        return RequestStatusResponse(id=record.id, status=record.status)

    return application


app = create_app()
