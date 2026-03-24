# Task: Tool Category/Topic Tagging System

## Objective

Add a category tagging system to tools so that search/retrieval can filter by IT domain before falling back to broader searches. Each tool gets one or more category tags assigned at registration time. When ToolSelector searches for tools, it first queries within the inferred category; if results are insufficient, it retries with related categories, and finally falls back to an unfiltered search.

## Part 1: Define the Category Taxonomy

Define an enum or constant set of tool categories. These represent **IT operational domains** — the actual technology areas an engineer troubleshoots or manages. Every category below is something a real IT team has tools for.

The category list should live in a single file (e.g., `tool_categories.py`) so it's easy to extend.

---

### Network — Layer 2/3 Infrastructure

- `routing` — BGP, OSPF, EIGRP, IS-IS, static routes, route tables, VRFs, route redistribution, PBR
- `switching` — VLANs, STP/RSTP/MSTP, port-channels/LACP, MAC tables, L2 forwarding, trunk ports, access ports
- `network_interfaces` — physical/logical interface status, speed/duplex, errors/counters, MTU, interface flaps
- `arp_mac` — ARP tables, MAC address tables, MAC-to-IP resolution, ARP inspection
- `qos` — traffic shaping, policing, DSCP marking, queue management, bandwidth guarantees, CoS
- `multicast` — IGMP, PIM, multicast routing, multicast groups, RP configuration
- `mpls` — label switching, LSPs, LDP, MPLS VPN, traffic engineering
- `network_fabric` — Cisco ACI, VMware NSX, VXLAN, EVPN, overlay networks, fabric management
- `spanning_tree` — STP topology, root bridge, port roles/states, BPDU guard, loop prevention

### Network — WAN & Connectivity

- `sd_wan` — overlay tunnels, WAN policies, application-aware routing, SD-WAN fabric, SLA probes, path selection
- `wan_optimization` — WAN accelerators, deduplication, compression, latency reduction, Riverbed/Silver Peak
- `mpls_vpn` — MPLS L3VPN, L2VPN, pseudowires, CE-PE connectivity, VRF leaking
- `isp_circuits` — WAN links, circuit IDs, bandwidth, SLA, carrier management, last mile
- `bgp_peering` — BGP neighbors, prefix advertisements, AS-path, communities, route policies, looking glass

### Network — Services

- `dns` — name resolution, DNS zones, records (A, AAAA, CNAME, MX, SRV, PTR), DNSSEC, split-horizon, forwarding
- `dhcp` — scopes, leases, reservations, relay agents, DHCP failover, option sets
- `ipam` — IP address management, subnet allocation, IP planning, conflict detection
- `ntp` — time synchronization, NTP servers/peers, stratum, clock drift
- `proxy` — forward proxy, web filtering, content inspection, URL categorization, PAC files, explicit/transparent proxy

### Network — Wireless

- `wireless` — access points, SSIDs, RF management, wireless controllers, roaming, channel planning, power levels
- `wireless_security` — WPA2/WPA3, 802.1X wireless, rogue AP detection, wireless IDS, captive portals

### Firewall & Perimeter

- `firewall` — security policies/rules, ACLs, zones, packet filtering, rule optimization, hit counts, rule ordering
- `nat` — source NAT, destination NAT, PAT, NAT pools, NAT traversal, NAT tables
- `firewall_objects` — address objects, service objects, object groups, network groups, FQDN objects
- `firewall_ha` — active/passive, active/active, failover, cluster sync, session sync, split-brain
- `waf` — web application firewall rules, OWASP protection, application layer filtering, bot mitigation
- `ddos_protection` — DDoS mitigation, rate limiting, scrubbing, traffic anomaly detection

### Security

- `vpn` — IPSec tunnels (site-to-site, hub-spoke, DMVPN), SSL VPN, remote access, tunnel status, phase1/phase2 SAs
- `authentication` — RADIUS, TACACS+, LDAP, SAML, SSO, MFA, 802.1X, user identity, auth policies
- `nac` — Network Access Control, 802.1X wired, posture assessment, guest access, device profiling, MAB
- `certificates` — PKI, TLS/SSL certs, CA management, cert lifecycle, CSR generation, cert expiration, OCSP/CRL
- `ids_ips` — intrusion detection/prevention, signatures, anomaly detection, threat events, false positive tuning
- `network_security` — security monitoring, threat intelligence feeds, IOC correlation, security incidents
- `endpoint_protection` — antivirus, EDR, endpoint firewall, device compliance, malware detection
- `email_security` — antispam, DMARC/DKIM/SPF, email gateway, quarantine, phishing protection
- `dlp` — data loss prevention, content inspection, sensitive data detection, policy violations, exfiltration prevention
- `siem` — security information & event management, log correlation, security analytics, incident detection, SOAR
- `vulnerability_scanning` — vulnerability assessment, CVE detection, patch gaps, compliance scanning, remediation tracking
- `microsegmentation` — zero trust segmentation, workload isolation, east-west traffic policies, NSX/Guardicore
- `encryption` — disk encryption, data-at-rest, data-in-transit, key management, KMS, HSM
- `casb` — cloud access security broker, shadow IT detection, cloud app control, cloud DLP

### Compute & Virtualization

- `hypervisor` — ESXi, Hyper-V, KVM, Proxmox, XenServer — VM lifecycle, snapshots, resource pools, vMotion, DRS
- `virtual_machines` — VM creation, deletion, cloning, templates, snapshots, resource allocation, VM inventory
- `containers` — Docker, Podman, container images, registries, container lifecycle, Dockerfile, volumes, networking
- `container_orchestration` — Kubernetes, OpenShift, K3s, Rancher — pods, deployments, services, namespaces, ingress, helm
- `server_hardware` — BIOS/UEFI, firmware, physical server management, iLO/iDRAC/IPMI/BMC, hardware health
- `vdi` — virtual desktop infrastructure, Horizon, Citrix, RDS, session hosts, desktop pools, user profiles
- `compute_cluster` — HA clusters, DRS, affinity/anti-affinity rules, resource scheduling, failover
- `gpu_compute` — GPU passthrough, vGPU, NVIDIA GRID, AI/ML compute resources, GPU allocation

### Storage

- `storage_san` — Fibre Channel, iSCSI, FCoE, LUNs, zoning, HBAs, WWN, storage fabric, ALUA, multipathing
- `storage_nas` — NFS, SMB/CIFS, file shares, quotas, permissions, export policies, access control
- `vsan` — VMware vSAN, storage policies, disk groups, fault domains, stretched cluster, vSAN health
- `storage_pools` — RAID groups, aggregates, pools, tiering, thin/thick provisioning, deduplication, compression
- `storage_replication` — synchronous/async replication, SRM, storage mirroring, RPO, replication status
- `backup_recovery` — backup jobs, restore, Veeam, Commvault, RMAN, retention policies, backup verification
- `disaster_recovery` — DR plans, failover/failback, DR testing, site recovery, RTO/RPO compliance
- `storage_performance` — IOPS, latency, throughput, cache hit ratio, queue depth, storage bottlenecks
- `object_storage` — S3-compatible, MinIO, blob storage, buckets, object lifecycle, tiering to cloud

### Hyperconverged Infrastructure

- `hci` — Nutanix, Azure Stack HCI, VxRail, SimpliVity — converged compute+storage+network, cluster expansion, HCI health
- `hci_storage` — Nutanix storage, storage containers, replication factor, EC, dedup/compression on HCI
- `hci_networking` — HCI network segmentation, AHV networking, uplink configuration, network segmentation

### Cloud & Hybrid

- `cloud_iaas` — AWS EC2, Azure VMs, GCP Compute — cloud compute instances, cloud networking, cloud security groups
- `cloud_networking` — VPCs, subnets, peering, transit gateways, cloud load balancers, cloud DNS, direct connect/ExpressRoute
- `cloud_identity` — Azure AD/Entra ID, AWS IAM, GCP IAM, cloud RBAC, service principals, managed identities
- `cloud_storage` — S3, Azure Blob, GCS, cloud disk, cloud file shares, cloud storage tiers
- `hybrid_connectivity` — site-to-cloud VPN, ExpressRoute, Direct Connect, Cloud Interconnect, hybrid DNS

### Monitoring & Observability

- `performance` — CPU, memory, disk, bandwidth utilization, throughput, latency metrics, capacity trending
- `status_health` — device reachability, uptime, ping, interface status, operational state, health checks, heartbeat
- `snmp` — SNMP polling, SNMP traps, MIBs, OIDs, SNMP v2c/v3, community strings, SNMP walk
- `netflow` — NetFlow, sFlow, IPFIX, flow collection, traffic analysis, top talkers, bandwidth consumers
- `logging` — syslog, event logs, log aggregation, log parsing, log forwarding, log retention, centralized logging
- `alerting` — SNMP traps, threshold alerts, event correlation, alert suppression, escalation, on-call
- `apm` — application performance monitoring, response times, error rates, transaction tracing, synthetic monitoring
- `network_monitoring` — PRTG, Zabbix, Nagios, LibreNMS, SolarWinds — device monitoring, service checks, dashboards
- `capacity_planning` — trend analysis, growth projection, resource forecasting, threshold planning, right-sizing

### Identity & Access Management

- `users_groups` — local users, AD/LDAP groups, organizational units, group memberships, account lifecycle
- `active_directory` — domain controllers, replication, GPOs, AD sites, trusts, schema, FSMO roles
- `pam` — privileged access management, admin sessions, credential vaults, just-in-time access, session recording
- `secrets_management` — HashiCorp Vault, Azure Key Vault, API keys, tokens, secrets rotation, service accounts
- `rbac` — role-based access control, permission sets, role assignments, least privilege, access reviews

### Licensing & Compliance

- `licensing` — license keys, entitlements, feature activation, license pools, usage tracking, license compliance
- `compliance_audit` — configuration compliance, CIS benchmarks, PCI-DSS, SOC2, audit trails, policy enforcement
- `asset_management` — hardware/software inventory, serial numbers, warranty, EOL/EOS tracking, asset lifecycle

### Configuration & Lifecycle

- `config_management` — running/startup configs, config backup, config diff, config templates, change management, rollback
- `firmware_updates` — OS upgrades, patch management, image management, upgrade paths, firmware repository
- `provisioning` — ZTP, device onboarding, templates, bulk deployment, PnP, auto-provisioning
- `automation` — Ansible, Terraform, Python scripts, REST APIs, orchestration, workflow automation, IaC
- `change_management` — change tickets, maintenance windows, approval workflows, pre/post change validation

### Load Balancing & Application Delivery

- `load_balancing` — virtual servers, pools, health monitors, traffic distribution, persistence/affinity
- `global_load_balancing` — GSLB, DNS-based load balancing, geo-routing, site failover
- `ssl_offloading` — SSL/TLS termination, certificate management on LB, cipher suites, HTTPS inspection
- `reverse_proxy` — Nginx, HAProxy, Traefik, Envoy, ingress controllers, backend routing

### Telephony & Collaboration

- `voip` — SIP trunks, call routing, voice gateways, voice quality (MOS), codecs, dial plans, PBX
- `video_conferencing` — meeting room systems, Zoom Rooms, Teams Rooms, SIP endpoints, video infrastructure
- `unified_comms` — Cisco UCM, MS Teams telephony, presence, IM, call center/contact center infrastructure

### Email & Messaging

- `email_infrastructure` — Exchange, mail flow, connectors, transport rules, mailbox management, mail queues
- `email_deliverability` — MX records, SPF/DKIM/DMARC (operations side), relay, bounce management

### Database

- `database` — SQL Server, Oracle, MySQL, PostgreSQL — instance management, queries, connections, tablespaces
- `database_ha` — Always On, RAC, replication, clustering, failover groups, read replicas
- `database_backup` — database backup/restore, point-in-time recovery, log shipping, backup testing
- `database_performance` — slow queries, index management, execution plans, connection pools, locking, deadlocks

### Endpoint & Client Management

- `desktop_management` — SCCM/Intune, GPO deployment, software distribution, OS imaging, patch deployment
- `mdm` — mobile device management, device enrollment, app management, compliance policies, remote wipe
- `printing` — print servers, printer management, print queues, driver management, print policies

### Physical Infrastructure & Data Center

- `power_ups` — UPS status, PDU management, power load, battery health, power redundancy, generator status
- `environmental` — temperature, humidity, CRAC/CRAH, hot/cold aisle, environmental sensors, cooling capacity
- `physical_cabling` — patch panels, cable management, fiber/copper, port mapping, cable testing
- `rack_space` — rack units, rack layout, physical placement, U-space management
- `physical_security` — badge access, cameras/CCTV, door controllers, security zones (physical)

### ITSM & Operations

- `ticketing` — incident management, service requests, ticket lifecycle, SLA tracking, escalation
- `cmdb` — configuration management database, CI relationships, dependency mapping, service topology
- `documentation` — network diagrams, runbooks, SOPs, knowledge base, topology maps
- `change_control` — change advisory board, change records, risk assessment, implementation plans

### IoT & OT

- `iot` — IoT device management, IoT gateways, sensor networks, device fleet, firmware OTA
- `ot_scada` — SCADA, PLC, industrial control systems, OT network segmentation, Purdue model, industrial protocols

---

## Part 2: Category Relatedness Map

Define a relatedness graph so Tier 2 searches know where to expand. When two categories commonly appear in the same troubleshooting workflow, they're related.

```
routing          → [switching, sd_wan, bgp_peering, mpls, network_interfaces, qos, multicast]
switching        → [routing, network_interfaces, arp_mac, spanning_tree, network_fabric, qos]
network_interfaces → [switching, routing, status_health, performance, arp_mac]
arp_mac          → [switching, network_interfaces, dns, dhcp]
qos              → [routing, switching, sd_wan, voip, network_interfaces, mpls]
multicast        → [routing, switching, network_interfaces, igmp]
mpls             → [routing, bgp_peering, mpls_vpn, sd_wan, qos]
network_fabric   → [switching, routing, microsegmentation, containers, container_orchestration]
spanning_tree    → [switching, network_interfaces, firewall_ha]

sd_wan           → [routing, vpn, wan_optimization, isp_circuits, qos, bgp_peering]
wan_optimization → [sd_wan, isp_circuits, performance, qos]
mpls_vpn         → [mpls, routing, bgp_peering, vpn]
isp_circuits     → [sd_wan, bgp_peering, wan_optimization, routing]
bgp_peering      → [routing, mpls, isp_circuits, sd_wan, mpls_vpn]

dns              → [dhcp, ipam, network_interfaces, email_deliverability, proxy]
dhcp             → [dns, ipam, network_interfaces, arp_mac, nac]
ipam             → [dns, dhcp, cloud_networking, network_interfaces]
ntp              → [status_health, config_management, authentication]
proxy            → [firewall, dns, web_security, casb, waf]

wireless         → [wireless_security, network_interfaces, authentication, nac]
wireless_security → [wireless, authentication, nac, ids_ips]

firewall         → [nat, firewall_objects, vpn, ids_ips, network_security, firewall_ha, waf]
nat              → [firewall, vpn, firewall_objects, load_balancing]
firewall_objects → [firewall, nat, vpn]
firewall_ha      → [firewall, status_health, compute_cluster]
waf              → [firewall, load_balancing, reverse_proxy, ddos_protection]
ddos_protection  → [firewall, waf, load_balancing, network_security]

vpn              → [firewall, authentication, sd_wan, nat, certificates, hybrid_connectivity]
authentication   → [active_directory, users_groups, nac, rbac, vpn, certificates]
nac              → [authentication, switching, wireless_security, endpoint_protection]
certificates     → [vpn, authentication, ssl_offloading, encryption, email_deliverability]
ids_ips          → [firewall, network_security, siem, logging]
network_security → [firewall, ids_ips, siem, vulnerability_scanning, dlp]
endpoint_protection → [network_security, mdm, desktop_management, vulnerability_scanning]
email_security   → [email_infrastructure, email_deliverability, dlp, siem]
dlp              → [email_security, casb, network_security, encryption]
siem             → [logging, ids_ips, network_security, alerting, vulnerability_scanning]
vulnerability_scanning → [compliance_audit, network_security, firmware_updates, endpoint_protection]
microsegmentation → [network_fabric, firewall, containers, network_security]
encryption       → [certificates, vpn, storage_san, secrets_management]
casb             → [cloud_identity, proxy, dlp, email_security]

hypervisor       → [virtual_machines, compute_cluster, hci, vsan, gpu_compute, server_hardware]
virtual_machines → [hypervisor, compute_cluster, performance, backup_recovery, storage_san]
containers       → [container_orchestration, network_fabric, storage_nas, virtual_machines]
container_orchestration → [containers, load_balancing, reverse_proxy, network_fabric, cloud_iaas]
server_hardware  → [hypervisor, firmware_updates, power_ups, environmental, status_health]
vdi              → [hypervisor, virtual_machines, active_directory, users_groups, gpu_compute]
compute_cluster  → [hypervisor, virtual_machines, firewall_ha, hci, status_health]
gpu_compute      → [hypervisor, virtual_machines, vdi, containers]

storage_san      → [storage_pools, storage_replication, storage_performance, hci_storage, virtual_machines]
storage_nas      → [storage_pools, backup_recovery, containers, users_groups]
vsan             → [hypervisor, hci, hci_storage, storage_pools, storage_performance]
storage_pools    → [storage_san, storage_nas, vsan, storage_performance, hci_storage]
storage_replication → [storage_san, disaster_recovery, backup_recovery, storage_performance]
backup_recovery  → [disaster_recovery, storage_replication, virtual_machines, database_backup]
disaster_recovery → [backup_recovery, storage_replication, compute_cluster, firewall_ha]
storage_performance → [storage_san, vsan, storage_pools, performance]
object_storage   → [cloud_storage, backup_recovery, storage_nas]

hci              → [hypervisor, vsan, hci_storage, hci_networking, compute_cluster]
hci_storage      → [hci, vsan, storage_pools, storage_san]
hci_networking   → [hci, switching, network_fabric, network_interfaces]

cloud_iaas       → [cloud_networking, cloud_identity, cloud_storage, hybrid_connectivity, virtual_machines]
cloud_networking → [cloud_iaas, hybrid_connectivity, vpn, dns, load_balancing]
cloud_identity   → [active_directory, authentication, rbac, cloud_iaas, casb]
cloud_storage    → [object_storage, cloud_iaas, backup_recovery, storage_nas]
hybrid_connectivity → [vpn, cloud_networking, sd_wan, isp_circuits, cloud_iaas]

performance      → [status_health, snmp, network_monitoring, capacity_planning, storage_performance]
status_health    → [performance, snmp, network_monitoring, alerting, network_interfaces]
snmp             → [status_health, network_monitoring, alerting, performance]
netflow          → [network_monitoring, performance, qos, routing, switching]
logging          → [siem, alerting, network_monitoring, compliance_audit]
alerting         → [status_health, snmp, logging, network_monitoring, siem]
apm              → [performance, logging, database_performance, load_balancing]
network_monitoring → [status_health, snmp, performance, alerting, netflow]
capacity_planning → [performance, storage_performance, cloud_iaas, licensing]

users_groups     → [active_directory, rbac, authentication, pam]
active_directory → [users_groups, authentication, cloud_identity, dns, rbac]
pam              → [authentication, secrets_management, rbac, siem, compliance_audit]
secrets_management → [pam, encryption, certificates, automation, cloud_identity]
rbac             → [users_groups, authentication, pam, cloud_identity]

licensing        → [asset_management, compliance_audit, capacity_planning]
compliance_audit → [licensing, config_management, vulnerability_scanning, logging]
asset_management → [licensing, cmdb, firmware_updates, server_hardware]

config_management → [firmware_updates, automation, provisioning, change_management, compliance_audit]
firmware_updates → [config_management, server_hardware, vulnerability_scanning, provisioning]
provisioning     → [config_management, automation, firmware_updates, dhcp, dns]
automation       → [config_management, provisioning, change_management, containers]
change_management → [config_management, ticketing, change_control, compliance_audit]

load_balancing   → [reverse_proxy, ssl_offloading, global_load_balancing, waf, dns]
global_load_balancing → [load_balancing, dns, disaster_recovery, cloud_networking]
ssl_offloading   → [load_balancing, certificates, reverse_proxy]
reverse_proxy    → [load_balancing, containers, container_orchestration, waf]

voip             → [qos, network_interfaces, dns, unified_comms, video_conferencing]
video_conferencing → [voip, unified_comms, network_interfaces, qos]
unified_comms    → [voip, video_conferencing, active_directory, dns]

email_infrastructure → [email_deliverability, email_security, dns, active_directory]
email_deliverability → [email_infrastructure, dns, certificates, email_security]

database         → [database_ha, database_performance, database_backup, storage_san]
database_ha      → [database, compute_cluster, storage_replication, disaster_recovery]
database_backup  → [database, backup_recovery, storage_nas, disaster_recovery]
database_performance → [database, performance, storage_performance, apm]

desktop_management → [active_directory, endpoint_protection, firmware_updates, mdm]
mdm              → [desktop_management, endpoint_protection, cloud_identity, users_groups]
printing         → [desktop_management, active_directory, dns, network_interfaces]

power_ups        → [environmental, server_hardware, status_health]
environmental    → [power_ups, server_hardware, rack_space, status_health]
physical_cabling → [network_interfaces, switching, rack_space]
rack_space       → [physical_cabling, server_hardware, environmental, power_ups]
physical_security → [environmental, status_health, compliance_audit]

ticketing        → [change_control, cmdb, siem, alerting]
cmdb             → [asset_management, ticketing, documentation, change_control]
documentation    → [cmdb, config_management, change_control]
change_control   → [change_management, ticketing, cmdb, compliance_audit]

iot              → [wireless, network_security, snmp, environmental]
ot_scada         → [iot, network_security, microsegmentation, physical_security]
```

---

## Part 3: Tag Assignment at Registration

When tools are registered (wherever tools get indexed/stored), assign categories based on the tool's name, description, and parameter schema. Options:

- **Static mapping** if tool names follow clear conventions
- **LLM-inferred** at registration time if tools are dynamic
- **Manual override** via a field in the tool definition schema

Store categories as metadata on the tool record (Qdrant payload, DB field, or wherever tools are persisted). A tool can have multiple categories (e.g., a VPN status checker → `vpn` + `status_health`).

---

## Part 4: Category-Aware Search (Cascading Strategy)

Modify the tool search/retrieval flow in ToolSelector:

1. **Tier 1 — Exact category match:** Infer the category from the user's intent/query. Filter tool search to only tools tagged with that category. If sufficient results → done.

2. **Tier 2 — Related categories:** If Tier 1 returns insufficient results, expand using the relatedness map defined above. Search tools tagged with related categories. If sufficient results → done.

3. **Tier 3 — Unfiltered fallback:** If Tier 2 still returns insufficient results, search without any category filter (current behavior).

Log which tier produced the final results for observability.

---

## Implementation Notes

- Check how tools are currently indexed and searched. Categories should be stored as payload fields for efficient filtered queries.
- The intent/evaluation LLM phase probably already produces something close to a category — check if we can extract it from there instead of adding another LLM call.
- Start by reading the tool registration flow and the search flow in `tool_selector.py` before making changes.
- The category list and relatedness map should live in a single file (e.g., `tool_categories.py`) so it's easy to extend.
- Expand the category list if you find tool definitions that don't fit any existing category.