# Lanes for other projects

Use `lane compose` for any project with Docker Compose. A lane is a Compose project named after its worktree path and your lane name. Different names or worktrees get separate containers, networks, volumes and host ports. No Jira ticket, Aruva stack or Aruva config is needed.

1. Work from the project checkout or pass `--project-dir <worktree>`. Use its Compose file or pass `-f compose.lane.yaml` before the command. Repeat `-f` for an override. Use the same directory and files for every command.
2. Use named volumes for writable data. Remove fixed container names and shared networks or volumes. Publish any web port to localhost without fixing the host port. For example:

   ```yaml
   services:
     web:
       image: nginx:alpine
       ports:
         - target: 80
           published: "0"
           host_ip: 127.0.0.1
   ```

3. Start the lane and get its address. Use a unique name per agent in the same checkout.

   ```sh
   lane compose up agent-one
   lane compose port agent-one web 80
   lane compose logs agent-one web
   lane compose exec agent-one web nginx -t
   lane compose down agent-one
   ```

4. Run `down` even if the start or test failed. It deletes the lane's volumes. Use test data and test credentials only. Separate Compose resources do not isolate a database or other service the app connects to outside Compose.

Without `lane` on PATH, use `~/.agents/skills/lane/scripts/lane` instead. The Aruva commands are unchanged and use [Aruva setup](setup.md).
