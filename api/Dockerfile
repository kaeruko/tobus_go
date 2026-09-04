FROM ghcr.io/pyo3/maturin:v1.13.3 AS rust-builder

WORKDIR /io
COPY native/transit_search_core ./native/transit_search_core
RUN maturin build \
    --release \
    --locked \
    --compatibility manylinux2014 \
    --manifest-path native/transit_search_core/Cargo.toml \
    --out /wheels

FROM public.ecr.aws/lambda/python:3.11

COPY requirements.txt ${LAMBDA_TASK_ROOT}/requirements.txt
RUN pip install -r ${LAMBDA_TASK_ROOT}/requirements.txt -t ${LAMBDA_TASK_ROOT}

COPY --from=rust-builder /wheels/*.whl /tmp/wheels/
RUN pip install /tmp/wheels/*.whl -t ${LAMBDA_TASK_ROOT} \
    && rm -rf /tmp/wheels

COPY . ${LAMBDA_TASK_ROOT}

CMD ["server.handler"]
