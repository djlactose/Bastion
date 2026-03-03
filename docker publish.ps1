docker buildx build --no-cache --sbom=true --provenance=mode=max -t djlactose/bastion -t djlactose/bastion:ubuntu --push ./
