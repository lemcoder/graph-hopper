# Deployment Plan Spec

## Purpose
Define deployment options and CI/CD pipelines for the graph-hopper MVP, with a primary focus on running on local networks (e.g., Raspberry Pi over LAN) or localhost.

## Requirements
- **Environment**: Support local Python execution (uvicorn/FastAPI) and optionally provide a Dockerfile for containerized deployment.
- **Network**: The service must be accessible over LAN (binding to `0.0.0.0`) without the strict need for reverse proxies (like Nginx) or HTTPS for the MVP phase.
- **Configuration**: Application configuration must be loaded via a YAML file corresponding to the schema in `src/config.py`.
- **Dependencies**: The project is self-contained and does not rely on an external database service.
- **CI/CD**: Implement a basic Continuous Integration pipeline (e.g., GitHub Actions) to automate testing and build verification.

## Configuration
The deployment relies on a YAML configuration file to define system parameters, which maps directly to the `Config` dataclass in `src/config.py`. Users must be able to provide a `config.yaml` file to set properties for:
- **Orchestrator**: Subagent limits, concurrency limits, timeouts, and embedding configurations.
- **Log**: File paths, max bytes, and backup counts.
- **Storage**: Base paths for subagents and failed tasks.
- **Secrets**: Store types and paths.
- **LLM**: Provider settings (e.g., OpenRouter), API keys, model selections, and timeouts.

*Note: Since default file paths in `config.py` (e.g., `/var/log/...`, `/var/lib/...`) often require root permissions, the deployment documentation should emphasize overriding these in the YAML file for standard user deployment on a Raspberry Pi.*

## Deployment Options

### 1. Bare Metal Python (Raspberry Pi / Localhost)
Ideal for lightweight deployment directly on the host OS.
- **Setup**: Requires a standard Python environment.
- **Install**: Create a virtual environment and install dependencies.
- **Run**: Start the server using Uvicorn, ensuring it binds to all interfaces to allow LAN access.
  - Example: `uvicorn src.main:app --host 0.0.0.0 --port 8000`
- **Config**: Pass the YAML config file path to the application (e.g., via an environment variable like `graph-hopper_CONFIG_PATH` or a CLI argument).

### 2. Docker Containerization
Provides an isolated environment, ensuring consistency across different machines (e.g., dev laptop vs. Raspberry Pi).
- **Setup**: A `Dockerfile` defining the Python runtime, copying the source code, installing dependencies, and exposing port 8000.
- **Run**: Mount the YAML config file and necessary storage directories as volumes.
  - Example: `docker run -p 8000:8000 -v ./config.yaml:/app/config.yaml -e graph-hopper_CONFIG_PATH=/app/config.yaml my-graph-hopper-app`
- *Note: Ensure the Docker image is compatible with or explicitly built for ARM architectures (e.g., `linux/arm64`) to support Raspberry Pi deployments.*

## CI/CD Pipeline
A basic GitHub Actions workflow will be implemented to ensure code quality and deployment readiness:
1. **Linting & Testing Job**: Triggers on Pull Requests and Pushes to the main branch.
   - Runs Python linters/formatters.
   - Executes the unit test suite.
2. **Build Verification Job**: Verifies that the Docker image builds successfully to prevent deployment breakages.

## Success Criteria
- graph-hopper MVP successfully starts and is accessible over LAN from a Raspberry Pi or local machine.
- Configuration is reliably parsed from a user-provided YAML file, overriding defaults seamlessly.
- Docker deployment is fully functional and supports local volume mounting for configs and logs.
- CI/CD pipeline correctly runs tests and validates Docker builds on every push/PR.
- Clear setup and run instructions are documented for both bare-metal and Docker approaches.