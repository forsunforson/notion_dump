# Deployment Guide

This directory contains the deployment script for the ChronoFold project.

## 1. Permission Setup

Before running the script, ensure it has execution permissions. Run the following command from the project root:

```bash
chmod +x deploy/run_task.sh
```

## 2. Crontab Configuration

To schedule the task to run automatically, you can use `crontab`.

1. Open the crontab editor:
   ```bash
   crontab -e
   ```

2. Add the following line to the end of the file:
   ```cron
  0 2 * * * /path/to/chronofold/deploy/run_task.sh --job sync
   ```

  **Important**: Replace `/path/to/chronofold` with the actual absolute path to your project directory.

   *Example:*
  If your project is at `/home/gcp_user/chronofold`, the line would be:
   ```cron
  0 2 * * * /home/gcp_user/chronofold/deploy/run_task.sh --job sync
   ```

### Monthly Review Example

To generate a monthly review on the X-th day of each month:

```cron
30 20 5 * * /path/to/chronofold/deploy/run_task.sh --job review --type monthly
```

If you choose a day greater than 28, some months may not run because that day doesn't exist (e.g., February 30th).

### Interactive Manager

You can also use the interactive manager to set up cron jobs (including monthly review) and manage the bot service:

```bash
./deploy/manage.sh
```

## 3. Logs & Monitoring

The script automatically creates a `logs/` directory in the project root if it doesn't exist.

- **Log File**: `logs/execution.log`
- **Lock File**: `logs/chronofold.pid` (contains the PID of the running process)

To view the execution logs in real-time or check recent activity:

```bash
# View the last 50 lines
tail -n 50 logs/execution.log

# Follow new log entries as they happen
tail -f logs/execution.log
```

## 4. Passwordless Bot Restart For Cron

If `deploy/run_task.sh` needs to auto-restart `chronofold-bot.service` after pulling new bot-related code, the cron user must be allowed to run `systemctl restart` without an interactive password prompt.

You can configure this in one step with:

```bash
bash deploy/setup_bot_sudoers.sh
```

Or specify a user and service name explicitly:

```bash
bash deploy/setup_bot_sudoers.sh bytedance chronofold-bot
```

What the script does:

- Detects the absolute path of `systemctl`
- Generates a sudoers snippet under `/etc/sudoers.d/`
- Validates syntax with `visudo -c -f`
- Installs the file with `440` permissions

After setup, verify with:

```bash
sudo -n systemctl restart chronofold-bot
sudo -n systemctl status chronofold-bot --no-pager
```

If the restart command exits with code `0`, `cron` can reuse the same permission when `run_task.sh` detects bot-related code changes.

## Script Details

- **Path Handling**: The script automatically resolves its location and switches to the project root directory.
- **Concurrency**: Uses a PID file mechanism to ensure only one instance runs at a time. It checks if the process ID in the lock file is still active.
- **Environment**: Automatically activates the `venv` in the project root before running the Python script.
- **Output**: Redirects both Standard Output (Stdout) and Standard Error (Stderr) to the log file with timestamps.
