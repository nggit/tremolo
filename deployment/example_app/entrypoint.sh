
UID="$(id -u app 2>/dev/null)"

if [ -z "$UID" ]; then
    UID=0
    USER=root
else
    USER=app
fi

if [ "$UID" -lt 10000 ]; then
    printf "Running app in development mode (UID=%d)\n" "$UID"
else
    printf "Running app in production mode (UID=%d)\n" "$UID"
fi

# use the same gid to host
# so we can modify files in both direction without hassle
HOST_GID=$(stat -c '%g' /app)

# keep the permissions in check each container (re)start
chmod 775 /app
find /app -type d ! -perm 775 -exec chmod 775 {} +
find /app -type f ! -perm 664 -exec chmod 664 {} +

chown -R "$USER:$HOST_GID" /app
su - "$USER" -- -c 'exec python3 /app/server.py'
