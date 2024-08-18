# Create the cluster
cd ../k8s
# kind create cluster \
#     --name airflow-cluster \
#     --config kind-cluster.yaml
# kubectl cluster-info

# Create airflow namespace
kubectl create namespace airflow
kubectl get namespaces

# Add ssh git secret
kubectl create secret generic airflow-ssh-git-secret \
    --from-file=gitSshKey=$HOME/.ssh/id_ed25519 \
    --namespace airflow
kubectl get secret airflow-ssh-git-secret \
    -o jsonpath="{.data.gitSshKey}" \
    --namespace airflow \
    | base64 --decode

# Add webserver secret
kubectl create secret generic airflow-webserver-secret \
    --from-literal=webserver-secret-key=$(python3 -c 'import secrets; print(secrets.token_hex(16))') \
    --namespace airflow
kubectl get secret airflow-webserver-secret \
    -o jsonpath="{.data.webserver-secret-key}" \
    --namespace airflow \
    | base64 --decode

# Add airflow repo
helm repo add apache-airflow https://airflow.apache.org
helm repo update
helm search repo airflow --versions

# Apply customized setting on airflow
export USERNAME=ryan910707
export CHART_VERSION=1.15.0
export AIRFLOW_VERSION=latest
rm -f values.yaml
helm show values apache-airflow/airflow --version ${CHART_VERSION} > values.yaml
yq eval -i '
  .defaultAirflowRepository = env(USERNAME) + "/spark-airflow" |
  .defaultAirflowTag = env(AIRFLOW_VERSION) |
  .airflowVersion = "2.9.3" |
  .images.airflow.repository = env(USERNAME) + "/spark-airflow" |
  .images.airflow.tag = env(AIRFLOW_VERSION) |
  .images.pod_template.repository = env(USERNAME) + "/spark-airflow" |
  .images.pod_template.tag = env(AIRFLOW_VERSION) |
  .workers.hostAliases = [{"ip":"10.121.252.198","hostnames":["hadoop-platform"]}] |
  .webserverSecretKeySecretName = "airflow-webserver-secret" |
  .webserver.livenessProbe.initialDelaySeconds = 25 |
  .webserver.startupProbe.failureThreshold = 10 |
  .webserver.startupProbe.periodSeconds = 12 |
  .dags.gitSync.enabled = true |
  .dags.gitSync.repo = "git@github.com:kevin1010607/airflow-dags.git" |
  .dags.gitSync.branch = "main" |
  .dags.gitSync.subPath = "dags" |
  .dags.gitSync.sshKeySecret = "airflow-ssh-git-secret" |
  .dags.gitSync.knownHosts = "github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl" |
  .config.kubernetes.worker_container_repository = "{{ .Values.images.pod_template.repository | default .Values.defaultAirflowRepository }}" |
  .config.kubernetes.worker_container_tag = "{{ .Values.images.pod_template.tag | default .Values.defaultAirflowTag }}" |
  .config.kubernetes_executor.worker_container_repository = "{{ .Values.images.pod_template.repository | default .Values.defaultAirflowRepository }}" |
  .config.kubernetes_executor.worker_container_tag = "{{ .Values.images.pod_template.tag | default .Values.defaultAirflowTag }}" |
  .config.core.enable_xcom_pickling= 'True'
' values.yaml 

# Install customized airflow
helm install airflow apache-airflow/airflow \
    --version ${CHART_VERSION} \
    --namespace airflow \
    -f values.yaml \
    --debug

# Run in the background
# sleep 60s
nohup kubectl port-forward svc/airflow-webserver 8081:8080 \
    --address 10.121.252.189 \
    --namespace airflow \
    2>&1 > /dev/null &

