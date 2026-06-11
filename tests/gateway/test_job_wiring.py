from app.gateway.server import handle_list_tools


async def test_job_tools_are_listed():
    names = {t.name for t in await handle_list_tools()}
    assert {"drive-export-large-file", "wait-for-job"} <= names


async def test_job_handlers_in_session_registry():

    from app.gateway.server import JOB_REGISTRY

    assert set(JOB_REGISTRY) == {"drive-export-large-file", "wait-for-job"}
