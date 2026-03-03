# Ensure a buildx builder exists that supports attestations
docker buildx inspect bastion-builder 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    docker buildx create --name bastion-builder --driver docker-container --use
} else {
    docker buildx use bastion-builder
}

docker buildx build --no-cache --sbom=true --provenance=mode=max -t djlactose/bastion -t djlactose/bastion:ubuntu --push ./
