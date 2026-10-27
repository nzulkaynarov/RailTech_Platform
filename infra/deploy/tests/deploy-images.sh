# Подключается (source) тестами infra/deploy/tests: образы деплоя из .github/workflows/deploy.yml (W14-S4).
# Образы описаны один раз — JSON-массивом в шаге «Матрица образов» job prepare (images='[ … ]'): image, context, target, contexts
# (build-contexts через \n), args, scope. Тесты читают его отсюда, а не ищут шаги «Образ …» по тексту.
#   deploy_images_json <workflow>        — массив JSON целиком (ошибка, если не найден или не разбирается)
#   deploy_image_field <workflow> <образ> <поле>  — значение поля (пусто, если образа нет)
#   deploy_image_names <workflow>        — имена образов, по одному в строке
deploy_images_json() {
  local json
  json="$(sed -n "/images='\[/,/^ *\]'/p" "$1" | sed "s/.*images='//; s/^ *\]'/]/")"
  [[ -n "$json" ]] && jq -e 'type == "array" and length > 0' <<<"$json" >/dev/null 2>&1 || return 1
  printf '%s\n' "$json"
}
deploy_image_field() {
  deploy_images_json "$1" | jq -r --arg i "$2" --arg f "$3" '.[] | select(.image == $i) | .[$f]'
}
deploy_image_names() {
  deploy_images_json "$1" | jq -r '.[].image'
}
