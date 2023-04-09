import zipfile
from zipfile import ZipFile
import requests
import base64
import json
import os
from django.conf import settings
from collections import namedtuple
from github import Github
from github import InputGitTreeElement
import shutil
from .constants import CLONE_ACCEPT_HEADER
from base64 import b64encode
from datetime import datetime
from connectors.core.connector import get_logger, ConnectorError
from connectors.cyops_utilities.files import download_file_from_cyops, check_file_traversal, save_file_in_env

logger = get_logger('github')

FileMetadata = namedtuple('FileMetadata', ['filename',
                                           'content_length',
                                           'content_type',
                                           'md5',
                                           'sha1',
                                           'sha256'])


class GitHub(object):
    def __init__(self, config):
        self.server_url = config.get('server_url')
        if not self.server_url.startswith('https://'):
            self.server_url = 'https://' + self.server_url
        if not self.server_url.endswith('/'):
            self.server_url += '/'
        self.git_username = config.get('username')
        self.password = config.get('password')
        self.verify_ssl = config.get('verify_ssl')
        self.clone_url = config.get('clone_url')

    def make_request(self, endpoint=None, method='GET', data=None, params=None, owner=None, org=None):
        try:
            if org:
                endpoint = 'repos/' + org + '/' + endpoint
            if owner:
                endpoint = 'repos/' + owner + '/' + endpoint
            url = self.server_url + endpoint
            headers = {'Authorization': 'Bearer ' + self.password, 'Content-Type': 'application/json',
                       'Accept': 'application/vnd.github.v3+json'}
            response = requests.request(method, url, params=params, data=data, headers=headers, verify=self.verify_ssl)
            if response.status_code == 204:
                return
            elif response.ok:
                return response.json()
            else:
                logger.error(response.text)
                raise ConnectorError({'status_code': response.status_code, 'message': response.text})
        except requests.exceptions.SSLError:
            raise ConnectorError('SSL certificate validation failed')
        except requests.exceptions.ConnectTimeout:
            raise ConnectorError('The request timed out while trying to connect to the server')
        except requests.exceptions.ReadTimeout:
            raise ConnectorError('The server did not send any data in the allotted amount of time')
        except requests.exceptions.ConnectionError:
            raise ConnectorError('Invalid endpoint or credentials')
        except Exception as err:
            logger.exception(str(err))
            raise ConnectorError(str(err))


def create_repository(config, params, *args, **kwargs):
    github = GitHub(config)
    if params.get('other_fields'):
        params.update(params.get('other_fields'))
        del params['other_fields']
    payload = {k: v for k, v in params.items() if
               v is not None and v != '' and v != {} and v != [] and k not in ['branch', 'org']}
    if params.get('repo_type') == 'Organization':
        endpoint = 'orgs/{0}/repos'.format(params.get('org'))
    else:
        endpoint = 'user/repos'
    response = github.make_request(endpoint=endpoint, method='POST', data=json.dumps(payload))
    return response


def create_repository_using_template(config, params, *args, **kwargs):
    github = GitHub(config)
    payload = {k: v for k, v in params.items() if
               v is not None and v != '' and v != {} and v != [] and k not in ['template_owner', 'template_repo']}
    return github.make_request(
        endpoint='repos/{0}/{1}/generate'.format(params.get('template_owner'), params.get('template_repo')),
        method='POST', data=json.dumps(payload))


def list_organization_repositories(config, params, *args, **kwargs):
    github = GitHub(config)
    params['type'] = params.get('type', '').lower()
    params['sort'] = (params.get('sort', '').lower()).replace(' ', '_')
    params['direction'] = params.get('direction', '').lower()
    query_params = {k: v for k, v in params.items() if
                    v is not None and v != '' and v != {} and v != [] and k != 'name'}
    return github.make_request(params=query_params, endpoint='orgs/{0}/repos'.format(params.get('org')))


def list_user_repositories(config, params, *args, **kwargs):
    github = GitHub(config)
    params['type'] = params.get('type', '').lower()
    params['sort'] = (params.get('sort', '').lower()).replace(' ', '_')
    params['direction'] = params.get('direction', '').lower()
    query_params = {k: v for k, v in params.items() if
                    v is not None and v != '' and v != {} and v != [] and k != 'username'}
    return github.make_request(params=query_params, endpoint='users/{0}/repos'.format(params.get('username')))


def list_authenticated_user_repositories(config, params, *args, **kwargs):
    github = GitHub(config)
    params['visibility'] = params.get('visibility', '').lower()
    params['type'] = params.get('type', '').lower()
    params['sort'] = (params.get('sort', '').lower()).replace(' ', '_')
    params['direction'] = params.get('direction', '').lower()
    query_params = {k: v for k, v in params.items() if v is not None and v != '' and v != {} and v != []}
    return github.make_request(params=query_params, endpoint='users/repos')


def update_repository(config, params, *args, **kwargs):
    github = GitHub(config)
    if params.get('other_fields'):
        params.update(params.get('other_fields'))
        del params['other_fields']
    payload = {k: v for k, v in params.items() if
               v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'org', 'repo']}
    return github.make_request(method='PATCH', data=json.dumps(payload), endpoint=params.get('repo'),
                               org=params.get('org'), owner=params.get('owner'))


def delete_repository(config, params, *args, **kwargs):
    github = GitHub(config)
    return github.make_request(method='DELETE', endpoint=params.get('repo'), org=params.get('org'),
                               owner=params.get('owner'))


def fork_organization_repository(config, params, *args, **kwargs):
    github = GitHub(config)
    payload = {k: v for k, v in params.items() if
               v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'repo']}
    return github.make_request(method='POST', data=json.dumps(payload),
                               endpoint='repos/{0}/{1}/forks'.format(params.get('owner'), params.get('repo')))


def list_fork_repositories(config, params, *args, **kwargs):
    github = GitHub(config)
    params['sort'] = params.get('sort', '').lower()
    query_params = {k: v for k, v in params.items() if
                    v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'repo']}
    return github.make_request(endpoint='repos/{0}/{1}/forks'.format(params.get('owner'), params.get('repo')),
                               params=query_params)


def create_update_file_contents(config, params, *args, **kwargs):
    github = GitHub(config)
    content = params.get('content').encode("ascii")
    content = base64.b64encode(content)
    content = content.decode("ascii")
    params.update({'content': content})
    payload = {k: v for k, v in params.items() if
               v is not None and v != '' and v != {} and v != [] and k not in ['path', 'owner', 'name', 'org']}
    return github.make_request(method='PUT', data=json.dumps(payload),
                               endpoint='{0}/contents/{1}'.format(params.get('name'),
                                                                  params.get('path')), org=params.get('org'),
                               owner=params.get('owner'))


def add_repository_collaborator(config, params, *args, **kwargs):
    github = GitHub(config)
    params['permission'] = params.get('permission', '').lower()
    payload = {k: v for k, v in params.items() if
               v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'repo', 'username', 'org']}
    return github.make_request(method='PUT', data=json.dumps(payload), org=params.get('org'), owner=params.get('owner'),
                               endpoint='{0}/collaborators/{1}'.format(params.get('repo'), params.get('username')))


def list_repository_collaborator(config, params, *args, **kwargs):
    github = GitHub(config)
    params['affiliation'] = params.get('affiliation', '').lower()
    params['permission'] = params.get('permission', '').lower()
    query_params = {k: v for k, v in params.items() if
               v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'repo', 'org']}
    return github.make_request(params=query_params, org=params.get('org'), owner=params.get('owner'),
                               endpoint='{0}/collaborators'.format(params.get('repo')))


def get_branch_revision(config, params, *args, **kwargs):
    github = GitHub(config)
    endpoint = 'repos/{0}/{1}/git/refs/heads/{2}'.format(
        params.get('org') if params.get('repo_type') == 'Organization' else params.get('owner'), params.get('repo'),
        params.get('base'))
    return github.make_request(endpoint=endpoint)


def create_branch(config, params, *args, **kwargs):
    github = GitHub(config)
    payload = {'ref': 'refs/heads/{0}'.format(params.get('new_branch_name')),
               'sha': params.get('sha') if params.get('checkout_branch') == 'Branch SHA' else
               get_branch_revision(config, params)['object']['sha']}
    return github.make_request(method='POST', data=json.dumps(payload),
                               endpoint='{0}/git/refs'.format(params.get('repo')), org=params.get('org'),
                               owner=params.get('owner'))


def merge_branch(config, params, *args, **kwargs):
    github = GitHub(config)
    payload = {k: v for k, v in params.items() if
               v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'repo']}
    return github.make_request(endpoint='repos/{0}/{1}/merges'.format(params.get('owner'), params.get('repo')),
                               data=json.dumps(payload), method='POST')


def list_branches(config, params, *args, **kwargs):
    github = GitHub(config)
    query_params = {k: v for k, v in params.items() if
                    v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'org', 'repo']}
    if query_params['protected'] is False:
        del query_params['protected']
    return github.make_request(endpoint='{0}/branches'.format(params.get('repo')), params=query_params,
                               org=params.get('org'), owner=params.get('owner'))


def delete_branch(config, params, *args, **kwargs):
    github = GitHub(config)
    return github.make_request(method='DELETE', org=params.get('org'), owner=params.get('owner'),
                               endpoint='{0}/git/refs/heads/{1}'.format(params.get('repo'), params.get('branch_name')))


def fetch_upstream(config, params, *args, **kwargs):
    github = GitHub(config)
    payload = {'branch': params.get('branch')}
    return github.make_request(endpoint='{0}/merge-upstream'.format(params.get('repo')), data=json.dumps(payload),
                               method='POST', org=params.get('org'), owner=params.get('owner'))


def clone_repository(config, params, *args, **kwargs):
    try:
        env = kwargs.get('env', {})
        url = "https://{0}:{1}@{2}/{3}/{4}/zip/refs/heads/{5}".format(config.get('username'),
                                                                      config.get('password'),
                                                                      config.get('clone_url').split('//')[-1],
                                                                      params.get('org') if params.get(
                                                                          'repo_type') == "Organization" else params.get(
                                                                          'owner'),
                                                                      params.get('name'),
                                                                      params.get(
                                                                          'branch') if params.get(
                                                                          'branch') else "main")
        headers = CLONE_ACCEPT_HEADER
        zip_file = '/tmp/github-{0}-{1}.zip'.format(params.get('name'), datetime.now().strftime('%Y-%m-%d-%H-%M-%S-%f'))
        response = requests.request("GET", url, headers=headers, data={})
        with open(zip_file, "wb") as zipFile:
            zipFile.write(response.content)
        if params.get('clone_zip') is True:
            save_file_in_env(env, zip_file)
            return {"path": zip_file}
        else:
            unzip_file_path = '/tmp/{0}-{1}'.format(params.get('name'), params.get('branch'))
            with zipfile.ZipFile(zip_file, "r") as zip_ref:
                zip_ref.extractall(settings.TMP_FILE_ROOT)
            save_file_in_env(env, unzip_file_path)
            save_file_in_env(env, zip_file)
            return {"path": unzip_file_path}
    except ConnectorError as e:
        raise ConnectorError(e)
    except Exception as e:
        raise ConnectorError(e)


def unzip_protected_file(file_iri=None, *args, **kwargs):
    try:
        env = kwargs.get('env', {})
        metadata = download_file_from_cyops(file_iri, None, *args, *args, **kwargs)
        file_name = metadata.get('cyops_file_path', None)
        source_filepath = os.path.join(settings.TMP_FILE_ROOT, file_name)
        target_filepath = os.path.join(settings.TMP_FILE_ROOT, datetime.now().strftime('%Y-%m-%d-%H-%M-%S-%f'))
        if os.path.exists(target_filepath):
            shutil.rmtree(target_filepath)
        with ZipFile(source_filepath) as zf:
            zipinfo = zf.infolist()
            for info in zipinfo:
                zf.extract(member=info, path=target_filepath)
        check_file_traversal(target_filepath)
        listOfFiles = list()
        for (dirpath, dirnames, filenames) in os.walk(target_filepath):
            listOfFiles += [os.path.join(dirpath, file) for file in filenames]
        save_file_in_env(env, target_filepath)
        save_file_in_env(env, file_name)
        return {"filenames": listOfFiles}
    except ConnectorError as e:
        raise ConnectorError(e)
    except Exception as e:
        raise ConnectorError(e)


def update_clone_repository(config, params, *args, **kwargs):
    try:
        env = kwargs.get('env', {})
        response = unzip_protected_file(type='File IRI', file_iri=params.get('file_iri'), env=env)
        path = response['filenames'][0].split('/')
        root_src_dir = '/tmp/{0}/{1}/'.format(path[2], path[3])
        root_dst_dir = params.get('clone_path') + '/'
        for src_dir, dirs, files in os.walk(root_src_dir):
            dst_dir = src_dir.replace(root_src_dir, root_dst_dir, 1)
            if not os.path.exists(dst_dir):
                os.makedirs(dst_dir)
            for file_ in files:
                src_file = os.path.join(src_dir, file_)
                dst_file = os.path.join(dst_dir, file_)
                if os.path.exists(dst_file):
                    # in case of the src and dst are the same file
                    if os.path.samefile(src_file, dst_file):
                        continue
                    os.remove(dst_file)
                shutil.move(src_file, dst_dir)
        return {'status': 'finish'}
    except Exception as err:
        raise ConnectorError(err)


def push_repository(config, params, *args, **kwargs):
    token = config.get('password')
    g = Github(token)
    if params.get('repo_type') == 'Organization':
        repo = g.get_organization(params.get('org')).get_repo(params.get('name'))
    else:
        repo = g.get_user().get_repo(params.get('name'))
    root = params.get('clone_path')
    file_list = []
    for root, dirs, files in os.walk(root):
        for f in files:
            if not any(x in os.path.join(root, f) for x in ['.DS_Store', '.git']):
                file_list.append(os.path.join(root, f))
    commit_message = params.get('commit_message')
    master_ref = repo.get_git_ref('heads/' + params.get('branch'))
    master_sha = master_ref.object.sha
    base_tree = repo.get_git_tree(master_sha)
    element_list = list()
    try:
        for entry in file_list:
            if entry.endswith('.png'):
                with open(entry, 'rb') as input_file:
                    data = input_file.read()
                    data = b64encode(data).decode() if isinstance(data, bytes) else b64encode(data.encode()).decode()
            else:
                with open(entry, 'r', encoding='utf-8', errors='ignore') as input_file:
                    data = input_file.read()
            en = entry.replace(params.get('clone_path') + '/', '')
            element = InputGitTreeElement(en, '100644', 'blob', content=data)
            element_list.append(element)
    except AssertionError as err:
        raise ConnectorError(err)
    tree = repo.create_git_tree(element_list, base_tree)
    parent = repo.get_git_commit(master_sha)
    commit = repo.create_git_commit(commit_message, tree, [parent])
    master_ref.edit(commit.sha)
    for entry in file_list:
        with open(entry, 'rb') as input_file:
            data = input_file.read()
        if entry.endswith('.png'):
            en = entry.replace(params.get('clone_path') + '/', '')
            old_file = repo.get_contents(en)
            commit = repo.update_file(en, 'Update PNG content', data, old_file.sha)
    return {"status": "finish"}


def create_pull_request(config, params, *args, **kwargs):
    github = GitHub(config)
    payload = {k: v for k, v in params.items() if
               v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'org', 'repo']}
    return github.make_request(method='POST', data=json.dumps(payload), endpoint='{0}/pulls'.format(params.get('repo')),
                               org=params.get('org'), owner=params.get('owner'))


def list_pull_request(config, params, *args, **kwargs):
    github = GitHub(config)
    params['state'] = params.get('state', '').lower()
    params['sort'] = (params.get('sort', '').lower()).replace(' ', '-')
    params['direction'] = params.get('direction', '').lower()
    query_params = {k: v for k, v in params.items() if
                    v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'org', 'repo',
                                                                                    'pull_number']}
    if params.get('pull_number'):
        endpoint = '{0}/pulls/{1}'.format(params.get('repo'), params.get('pull_number'))
    else:
        endpoint = '{0}/pulls'.format(params.get('repo'))
    return github.make_request(params=query_params, endpoint=endpoint, org=params.get('org'), owner=params.get('owner'))


def add_reviewers(config, params, *args, **kwargs):
    github = GitHub(config)
    payload = {k: v for k, v in params.items() if
               v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'org', 'repo', 'pull_number']}
    body_params = {}
    for k, v in payload.items():
        if v:
            if isinstance(v, str):
                body_params.update({k: list(map(lambda x: x.strip(' '), v.split(",")))})
            elif isinstance(v, list):
                body_params.update({k: list(map(str, v))})
    endpoint = '{0}/pulls/{1}/requested_reviewers'.format(params.get('repo'), params.get('pull_number'))
    return github.make_request(method='POST', data=json.dumps(body_params), endpoint=endpoint, org=params.get('org'),
                               owner=params.get('owner'))


def list_review_comments(config, params, *args, **kwargs):
    github = GitHub(config)
    params['sort'] = params.get('sort', '').lower()
    params['direction'] = params.get('direction', '').lower()
    query_params = {k: v for k, v in params.items() if
                    v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'org', 'repo',
                                                                                    'pull_number']}
    endpoint = '{0}/pulls/{1}/comments'.format(params.get('repo'), params.get('pull_number'))
    return github.make_request(params=query_params, endpoint=endpoint, org=params.get('org'),
                               owner=params.get('owner'))


def list_pr_reviews(config, params, *args, **kwargs):
    github = GitHub(config)
    query_params = {k: v for k, v in params.items() if
                    v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'org', 'repo',
                                                                                    'pull_number']}
    endpoint = '{0}/pulls/{1}/reviews'.format(params.get('repo'), params.get('pull_number'))
    return github.make_request(params=query_params, endpoint=endpoint, org=params.get('org'),
                               owner=params.get('owner'))


def add_pr_review(config, params, *args, **kwargs):
    github = GitHub(config)
    params['event'] = (params.get('event', '').upper()).replace(' ', '_')
    payload = {k: v for k, v in params.items() if
               v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'org', 'repo', 'pull_number']}
    endpoint = '{0}/pulls/{1}/reviews'.format(params.get('repo'), params.get('pull_number'))
    return github.make_request(method='POST', data=json.dumps(payload), endpoint=endpoint, org=params.get('org'),
                               owner=params.get('owner'))


def merge_pull_request(config, params, *args, **kwargs):
    github = GitHub(config)
    params['merge_method'] = params.get('merge_method', '').lower()
    payload = {k: v for k, v in params.items() if
               v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'org', 'repo', 'pull_number']}
    endpoint = '{0}/pulls/{1}/merge'.format(params.get('repo'), params.get('pull_number'))
    return github.make_request(method='PUT', data=json.dumps(payload), endpoint=endpoint, org=params.get('org'),
                               owner=params.get('owner'))


def create_issue(config, params, *args, **kwargs):
    github = GitHub(config)
    payload = {k: v for k, v in params.items() if
               v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'org', 'repo']}
    endpoint = '{0}/issues'.format(params.get('repo'))
    return github.make_request(method='POST', data=json.dumps(payload), endpoint=endpoint, org=params.get('org'),
                               owner=params.get('owner'))


def list_repository_issue(config, params, *args, **kwargs):
    github = GitHub(config)
    params['state'] = params.get('state', '').lower()
    params['sort'] = params.get('sort', '').lower()
    params['direction'] = params.get('direction', '').lower()
    query_params = {k: v for k, v in params.items() if
                    v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'org', 'repo']}
    endpoint = '{0}/issues'.format(params.get('repo'))
    response = github.make_request(params=query_params, endpoint=endpoint, org=params.get('org'),
                                   owner=params.get('owner'))
    for e in range(len(response) - 1, -1, -1):
        if response[e].get('pull_request') is not None:
            response.pop(e)
    return response


def update_issue(config, params, *args, **kwargs):
    github = GitHub(config)
    params['state'] = params.get('state', '').lower()
    params['state_reason'] = (params.get('state_reason', '').lower()).replace(' ', '_')
    payload = {k: v for k, v in params.items() if
               v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'org', 'repo', 'issue_number']}
    endpoint = '{0}/issues/{1}'.format(params.get('repo'), params.get('issue_number'))
    return github.make_request(method='PATCH', data=json.dumps(payload), endpoint=endpoint, org=params.get('org'),
                               owner=params.get('owner'))


def create_issue_comment(config, params, *args, **kwargs):
    github = GitHub(config)
    payload = {"body": params.get('body')}
    endpoint = '{0}/issues/{1}/comments'.format(params.get('repo'), params.get('issue_number'))
    return github.make_request(method='POST', data=json.dumps(payload), endpoint=endpoint, org=params.get('org'),
                               owner=params.get('owner'))


def create_release(config, params, *args, **kwargs):
    github = GitHub(config)
    payload = {k: v for k, v in params.items() if
               v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'org', 'repo']}
    endpoint = '{0}/releases'.format(params.get('repo'))
    return github.make_request(method='POST', data=json.dumps(payload), endpoint=endpoint, org=params.get('org'),
                               owner=params.get('owner'))


def list_releases(config, params, *args, **kwargs):
    github = GitHub(config)
    query_params = {k: v for k, v in params.items() if
                    v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'org', 'repo']}
    endpoint = '{0}/releases'.format(params.get('repo'))
    return github.make_request(params=query_params, endpoint=endpoint, org=params.get('org'),
                               owner=params.get('owner'))


def list_stargazers(config, params, *args, **kwargs):
    github = GitHub(config)
    query_params = {k: v for k, v in params.items() if
                    v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'org', 'repo']}
    endpoint = '{0}/stargazers'.format(params.get('repo'))
    return github.make_request(params=query_params, endpoint=endpoint, org=params.get('org'),
                               owner=params.get('owner'))


def star_repository(config, params, *args, **kwargs):
    github = GitHub(config)
    endpoint = 'user/starred/{0}/{1}'.format(
        params.get('org') if params.get('repo_type') == 'Organization' else params.get('owner'), params.get('repo'))
    return github.make_request(method='PUT', endpoint=endpoint)


def list_watchers(config, params, *args, **kwargs):
    github = GitHub(config)
    query_params = {k: v for k, v in params.items() if
                    v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'org', 'repo']}
    endpoint = '{0}/subscribers'.format(params.get('repo'))
    return github.make_request(params=query_params, endpoint=endpoint, org=params.get('org'),
                               owner=params.get('owner'))


def set_repo_subscription(config, params, *args, **kwargs):
    github = GitHub(config)
    payload = {k: v for k, v in params.items() if
               v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'org', 'repo']}
    endpoint = '{0}/subscription'.format(params.get('repo'))
    return github.make_request(method='PUT', data=json.dumps(payload), endpoint=endpoint, org=params.get('org'),
                               owner=params.get('owner'))


def _check_health(config):
    try:
        github = GitHub(config)
        response = github.make_request(endpoint='users/repos')
        if response:
            return True
        else:
            raise ConnectorError("{} error: {}".format(response.status_code, response.reason))
    except Exception as err:
        raise ConnectorError(err)


operations = {
    'create_repository': create_repository,
    'create_repository_using_template': create_repository_using_template,
    'list_organization_repositories': list_organization_repositories,
    'list_user_repositories': list_user_repositories,
    'list_authenticated_user_repositories': list_authenticated_user_repositories,
    'update_repository': update_repository,
    'delete_repository': delete_repository,
    'fork_organization_repository': fork_organization_repository,
    'list_fork_repositories': list_fork_repositories,
    'create_update_file_contents': create_update_file_contents,
    'add_repository_collaborator': add_repository_collaborator,
    'list_repository_collaborator': list_repository_collaborator,
    'get_branch_revision': get_branch_revision,
    'create_branch': create_branch,
    'merge_branch': merge_branch,
    'delete_branch': delete_branch,
    'create_issue': create_issue,
    'update_issue': update_issue,
    'create_issue_comment': create_issue_comment,
    'list_repository_issue': list_repository_issue,
    'list_branches': list_branches,
    'fetch_upstream': fetch_upstream,
    'clone_repository': clone_repository,
    'update_clone_repository': update_clone_repository,
    'push_repository': push_repository,
    'create_pull_request': create_pull_request,
    'list_pull_request': list_pull_request,
    'add_reviewers': add_reviewers,
    'list_review_comments': list_review_comments,
    'list_pr_reviews': list_pr_reviews,
    'add_pr_review': add_pr_review,
    'merge_pull_request': merge_pull_request,
    'list_releases': list_releases,
    'create_release': create_release,
    'list_stargazers': list_stargazers,
    'star_repository': star_repository,
    'list_watchers': list_watchers,
    'set_repo_subscription': set_repo_subscription
}
