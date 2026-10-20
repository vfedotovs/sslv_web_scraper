

docker images \
  | grep -E "\-ts|\-ws|\-db|\-backup" \
  | awk '{print $3}' \
  | while read -r img_id ;
      do echo "Removing $img_id ID";
      docker rmi -f "$img_id";
    done

# Also prune any dangling images left behind
docker image prune -f || true

