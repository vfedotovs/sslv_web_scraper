

docker images \
  | grep -E "\-ts|\-ws|\-db" \
  | awk '{print $3}' \
  | while read -r img_id ;
      do echo "Removing $img_id ID \n";
      docker rmi -f "$img_id";
    done

