FROM python:3.12-slim
COPY inventory.py chaosproxy.py shop.py console.py /app/
USER 65534
ENV PYTHONUNBUFFERED=1
CMD ["python", "/app/shop.py"]
