# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, you can obtain one at http://mozilla.org/MPL/2.0/.
from datetime import timedelta
from django.utils import timezone

import django_rq
import newrelic.agent

from .models import Cluster
from .. import email, provisioning


@newrelic.agent.background_task(group='RQ')
def delete_clusters():
    now = timezone.now()
    for cluster in Cluster.objects.active().filter(end_date__lte=now):
        # The cluster is expired
        cluster.deactivate()


@newrelic.agent.background_task(group='RQ')
def send_expiration_mails():
    deadline = timezone.now() + timedelta(hours=1)
    soon_expired = Cluster.objects.active().filter(
        end_date__lte=deadline,
        expiration_mail_sent=False,
    )
    for cluster in soon_expired:
        email.send_email(
            email_address=cluster.created_by.email,
            subject="Cluster {} is expiring soon!".format(cluster.identifier),
            body=(
                "Your cluster {} will be terminated in roughly one hour, around {}. "
                "Please save all unsaved work before the machine is shut down.\n"
                "\n"
                "This is an automated message from the Telemetry Analysis service. "
                "See https://analysis.telemetry.mozilla.org/ for more details."
            ).format(cluster.identifier, deadline)
        )
        cluster.expiration_mail_sent = True
        cluster.save(update_fields=['expiration_mail_sent'])


@newrelic.agent.background_task(group='RQ')
def update_master_address(cluster_id, force=False):
    """
    Update the public IP address for the cluster with the given cluster ID
    """
    cluster = Cluster.objects.get(id=cluster_id)
    # quick way out in case this job was called accidently
    if cluster.master_address and not force:
        return
    # first get the cluster info from AWS
    info = cluster.get_info()
    master_address = info.get('public_dns') or ''
    # then store the public IP of the cluster if found in response
    if master_address:
        cluster.master_address = master_address
        cluster.save(update_fields=['master_address'])


@newrelic.agent.background_task(group='RQ')
def update_clusters_info():
    """
    Update the cluster metadata from AWS for the pending
    clusters.

    - To be used periodically.
    - Won't update state if not needed.
    - Will queue updating the Cluster's public IP address if needed.
    """
    # only update the cluster info for clusters that are pending
    active_clusters = Cluster.objects.active()

    # Short-circuit for no active clusters (e.g. on weekends)
    if not active_clusters.exists():
        return

    # get the start dates of the active clusters, set to the start of the day
    # to counteract time differences between atmo and AWS and use the oldest
    # start date to limit the ListCluster API call to AWS
    oldest_start_date = active_clusters.datetimes('start_date', 'day')

    # build a mapping between jobflow ID and cluster info
    cluster_mapping = {}
    for cluster_info in provisioning.cluster_list(oldest_start_date[0]):
        cluster_mapping[cluster_info['jobflow_id']] = cluster_info

    # go through pending clusters and update the state if needed
    for cluster in active_clusters:
        info = cluster_mapping.get(cluster.jobflow_id)
        # ignore if no info was found for some reason,
        # the cluster was deleted in AWS but it wasn't deleted here yet
        if info is None:
            continue

        # don't update the state if it's equal to the already stored state
        if info['state'] == cluster.most_recent_status:
            continue

        # run an UPDATE query for the cluster
        cluster.most_recent_status = info['state']
        cluster.save(update_fields=['most_recent_status'])

        # if not given enqueue a job to update the public IP address
        if not cluster.master_address:
            django_rq.enqueue(update_master_address, cluster.id)
