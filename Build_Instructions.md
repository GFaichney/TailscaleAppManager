# Tailscale Serve Wrapper for Multiple Apps

A wrapper app to easily launch a list of different apps with web frontends and then serve them all on different paths using `tailscale serve`

## Application Details

- Python 3
- Web interface with API backend
- Data persisted to YAML config file
- Should be responsive - should render on a large screen, but equally work for a phone screen using touch
- App must have a setup script in both bash and powershell that sets up the python venv if not preent and installs all requirements from requirements.txt
- App must have a run script in both bash and powershell that activates the venv and runs the applcation
- All requirements must be saved to requirements.txt
- Should run on both Winows an Linux
- Application run script should also serve the app over Tailscale using `tailscale serve` command

## Application Functionality

- UI allows the user to add and remove applications
- Each application has the following details:
  - application_name: Name of the application
  - application_port: Port the application listens on
  - executable: (optional) Path of the launch script relative to the application folder
    - **If** not provided, assume `./run.sh`
  - application_folder: (optional) Filesystem location of the application
  - github_location: (optional) Location of the application in github
  - web_path: A short path to be used in a URL
  - setup_executable: (optional) Path of the application setup script relative to the application folder
    - **If** not provided, assume `./setup.sh`
  - While application_folder and github_location are both optional, one of the two must be provided. Both cannot be provided at once.
- When an application is added:
  - Ensure its port doesn't clash with an existing app or this app, otherwise error and refuse to add 
  - **If** the github_location is provided:
    - Switch to a subfolder called `installed_apps` 
    - Clone the code
    - Change to the newly created folder
  - **Else** change to the application_folder
  - Run the setup_executable
  - Run the application in the background. Record its PID
  - In the background, run `tailscale serve --bg --set-path /{{web_path}}}} http://127.0.0.1:{{application:port}}`
- When an application is deleted:
  - Prevent calls over tailscale using `tailscale serve drain`  
  - Kill the process using the save PID
  - Remove its configuration
- When the application is started up:
  - Launch each app from its folder, in the background, using its executable
  - In the background, run `tailscale serve --bg --set-path /{{web_path}}}} http://127.0.0.1:{{application:port}}`
  - Run a check on each application with a github_location and visibly flag any that have updated code available in Github
- When the application is stopped, shut down all running applications
- Include an application log pane that keeps track of errors and significant events (e.g. app additions, deletions, startupm and shutdown)
- Include a button to check for updates on Github for all apps that have a github_location configured
  - **If** clicked, check for new code for each application that has a github_location
  - **If** an application has new code, pull it, kill the application then restart it using its execution script
  