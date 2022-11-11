from zipfile import ZipFile
import requests
import base64
import json
import os
import glob
from django.conf import settings
from collections import namedtuple
from github import Github
from github import InputGitTreeElement
from PIL import Image
from io import BytesIO
import shutil
from datetime import date
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
        self.username = config.get('username')
        self.password = config.get('password')
        self.verify_ssl = config.get('verify_ssl')

    def make_request(self, endpoint=None, method='GET', data=None, params=None, files=None, headers=None):
        try:
            url = self.server_url + endpoint
            headers = {'Authorization': 'Bearer ' + self.password, 'Content-Type': 'application/json',
                       'Accept': 'application/vnd.github.v3+json'}
            response = requests.request(method, url, params=params, files=files,
                                        data=data, headers=headers, verify=self.verify_ssl)
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


def create_organization_repository(config, params):
    github = GitHub(config)
    if params.get('other_fields'):
        params.update(params.get('other_fields'))
        del params['other_fields']
    payload = {k: v for k, v in params.items() if v is not None and v != '' and v != {} and v != [] and k != 'org'}
    response = github.make_request(endpoint='orgs/{0}/repos'.format(params.get('org')), method='POST',
                                   data=json.dumps(payload))
    create_readme_file(config, params)
    return response


def list_organization_repositories(config, params):
    github = GitHub(config)
    query_params = {k: v for k, v in params.items() if
                    v is not None and v != '' and v != {} and v != [] and k != 'name'}
    return github.make_request(params=query_params, endpoint='orgs/{0}/repos'.format(params.get('org')))


def fork_organization_repository(config, params):
    github = GitHub(config)
    payload = {k: v for k, v in params.items() if
               v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'repo']}
    return github.make_request(endpoint='repos/{0}/{1}/forks'.format(params.get('owner'), params.get('repo')),
                               method='POST', data=json.dumps(payload))


def list_fork_repositories(config, params):
    github = GitHub(config)
    query_params = {k: v for k, v in params.items() if
                    v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'repo']}
    return github.make_request(endpoint='repos/{0}/{1}/forks'.format(params.get('owner'), params.get('repo')),
                               params=query_params)


def create_readme_file(config, params):
    github = GitHub(config)
    payload = {'message': 'README.md file created', 'content': 'IA==', 'branch': params.get('branch')}
    return github.make_request(method='PUT', data=json.dumps(payload),
                               endpoint='repos/{0}/{1}/contents/README.md'.format(params.get('owner'),
                                                                                  params.get('name')))


def create_user_repository(config, params):
    github = GitHub(config)
    if params.get('other_fields'):
        params.update(params.get('other_fields'))
        del params['other_fields']
    payload = {k: v for k, v in params.items() if v is not None and v != '' and v != {} and v != []}
    response = github.make_request(endpoint='user/repos', method='POST', data=json.dumps(payload))
    create_readme_file(config, params)
    return response


def create_repository_using_template(config, params):
    github = GitHub(config)
    payload = {k: v for k, v in params.items() if
               v is not None and v != '' and v != {} and v != [] and k not in ['template_owner', 'template_repo']}
    return github.make_request(
        endpoint='repos/{0}/{1}/generate'.format(params.get('template_owner'), params.get('template_repo')),
        method='POST', data=json.dumps(payload))


def list_authenticated_user_repositories(config, params):
    github = GitHub(config)
    query_params = {k: v for k, v in params.items() if v is not None and v != '' and v != {} and v != []}
    return github.make_request(params=query_params, endpoint='users/repos')


def list_user_repositories(config, params):
    github = GitHub(config)
    query_params = {k: v for k, v in params.items() if
                    v is not None and v != '' and v != {} and v != [] and k != 'username'}
    return github.make_request(params=query_params, endpoint='users/{0}/repos'.format(params.get('username')))


def update_repository(config, params):
    github = GitHub(config)
    if params.get('other_fields'):
        params.update(params.get('other_fields'))
        del params['other_fields']
    payload = {k: v for k, v in params.items() if
               v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'repo']}
    return github.make_request(endpoint='repos/{0}/{1}'.format(params.get('owner'), params.get('repo')),
                               method='PATCH', data=json.dumps(payload))


def add_repository_collaborator(config, params):
    github = GitHub(config)
    payload = {k: v for k, v in params.items() if
               v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'repo', 'username']}
    return github.make_request(
        endpoint='repos/{0}/{1}/collaborators/{2}'.format(params.get('owner'), params.get('repo'),
                                                          params.get('username')),
        method='PUT', data=json.dumps(payload))


def delete_repository(config, params):
    github = GitHub(config)
    return github.make_request(endpoint='repos/{0}/{1}'.format(params.get('owner'), params.get('repo')),
                               method='DELETE')


def get_branch_revision(config, params):
    github = GitHub(config)
    return github.make_request(
        endpoint='repos/{0}/{1}/git/refs/heads/{2}'.format(params.get('owner'), params.get('repo'), params.get('base')))


def create_branch(config, params):
    github = GitHub(config)
    payload = {'ref': 'refs/heads/{0}'.format(params.get('new_branch_name')),
               'sha': params.get('sha') if params.get('checkout_branch') == 'Branch SHA' else
               get_branch_revision(config, params)['object']['sha']}
    return github.make_request(method='POST', data=json.dumps(payload),
                               endpoint='repos/{0}/{1}/git/refs'.format(params.get('owner'), params.get('repo')))


def merge_branch(config, params):
    github = GitHub(config)
    payload = {k: v for k, v in params.items() if
               v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'repo']}
    return github.make_request(endpoint='repos/{0}/{1}/merges'.format(params.get('owner'), params.get('repo')),
                               data=json.dumps(payload), method='POST')


def list_branches(config, params):
    github = GitHub(config)
    query_params = {k: v for k, v in params.items() if
                    v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'repo']}
    if query_params['protected'] is False:
        del query_params['protected']
    return github.make_request(endpoint='repos/{0}/{1}/branches'.format(params.get('owner'), params.get('repo')),
                               params=query_params)


def fetch_upstream(config, params):
    github = GitHub(config)
    payload = {'branch': params.get('branch')}
    return github.make_request(endpoint='repos/{0}/{1}/merge-upstream'.format(params.get('owner'), params.get('repo')),
                               data=json.dumps(payload), method='POST')


def clone_repository(config, params):
    try:
        token = config.get('password')
        g = Github(token)
        repo = g.get_user().get_repo(params.get('name'))
        contents = repo.get_contents("")
        while contents:
            file_content = contents.pop(0)
            if file_content.type == "dir":
                contents.extend(repo.get_contents(file_content.path))
            elif 'DS_Store' not in file_content.path:
                completeName = os.path.join('/tmp/{0}/{1}'.format(params.get('name'), file_content.path))
                wkspFldr = os.path.dirname(completeName)
                if not os.path.exists(wkspFldr):
                    os.makedirs(wkspFldr)
                data = file_content.content
                if '.png' not in file_content.path:
                    data = base64.b64decode(data)
                    with open(completeName, "wb") as file1:
                        file1.write(data)
                else:
                    with Image.open(BytesIO(base64.b64decode(data))) as im:
                        im.save('/tmp/{0}/{1}'.format(params.get('name'), file_content.path), 'PNG')
        if params.get('clone_zip') is True:
            root_path = '/tmp/{0}'.format(params.get('name'))
            dst_path = '/tmp/cicd/{0}'.format(params.get('name'))
            dest_folder = '/tmp/cicd'
            shutil.move(root_path, dst_path)
            shutil.make_archive(dst_path, "zip", root_dir=dest_folder, base_dir=params.get('name'))
            shutil.rmtree('/tmp/cicd/{0}/'.format(params.get('name')))
            return {"path": "/tmp/cicd/{0}.zip".format(params.get('name'))}
        else:
            return {"path": "/tmp/{0}".format(params.get('name'))}
    except Exception as err:
        raise ConnectorError(err)


def unzip_protected_file(file_iri=None, *args, **kwargs):
    try:
        metadata = download_file_from_cyops(file_iri, None, *args, **kwargs)
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
        env = kwargs.get('env', {})
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


def update_clone_repository(config, params):
    try:
        todays_date = date.today()
        del_paths = glob.glob(os.path.join('/tmp/', str(todays_date.year) + '*'))
        for del_path in del_paths:
            shutil.rmtree(del_path)
        response = unzip_protected_file(type='File IRI', file_iri=params.get('file_iri'))
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


def push_repository(config, params):
    token = config.get('password')
    g = Github(token)
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
                with open(entry, 'r') as input_file:
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
        print(entry)
        with open(entry, 'rb') as input_file:
            data = input_file.read()
        if entry.endswith('.png'):
            en = entry.replace(params.get('clone_path') + '/', '')
            old_file = repo.get_contents(en)
            commit = repo.update_file(en, 'Update PNG content', data, old_file.sha)
    shutil.rmtree('/tmp/{0}/'.format(params.get('name')))
    return {"status": "finish"}


def create_pull_request(config, params):
    github = GitHub(config)
    payload = {k: v for k, v in params.items() if
               v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'repo']}
    return github.make_request(method='POST', data=json.dumps(payload),
                               endpoint='repos/{0}/{1}/pulls'.format(params.get('owner'), params.get('repo')))


def list_pull_request(config, params):
    github = GitHub(config)
    qyery_params = {k: v for k, v in params.items() if
                    v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'repo']}
    return github.make_request(params=qyery_params,
                               endpoint='repos/{0}/{1}/pulls'.format(params.get('owner'), params.get('repo')))


def add_reviewers(config, params):
    github = GitHub(config)
    payload = {k: v for k, v in params.items() if
               v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'repo', 'pull_number']}
    body_params = {}
    for k, v in payload.items():
        if v:
            if isinstance(v, str):
                body_params.update({k: list(map(lambda x: x.strip(' '), v.split(",")))})
            elif isinstance(v, list):
                body_params.update({k: list(map(str, v))})
    return github.make_request(method='POST', data=json.dumps(body_params),
                               endpoint='repos/{0}/{1}/pulls/{2}/requested_reviewers'.format(params.get('owner'),
                                                                                             params.get('repo'),
                                                                                             params.get('pull_number')))


def list_review_comments(config, params):
    github = GitHub(config)
    query_params = {k: v for k, v in params.items() if
                    v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'repo', 'pull_number']}
    return github.make_request(params=query_params,
                               endpoint='repos/{0}/{1}/pulls/{2}/comments'.format(params.get('owner'),
                                                                                  params.get('repo'),
                                                                                  params.get('pull_number')))


def merge_pull_request(config, params):
    github = GitHub(config)
    payload = {k: v for k, v in params.items() if
               v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'repo', 'pull_number']}
    return github.make_request(method='PUT', data=json.dumps(payload),
                               endpoint='repos/{0}/{1}/pulls/{2}/merge'.format(params.get('owner'), params.get('repo'),
                                                                               params.get('pull_number')))


def list_releases(config, params):
    github = GitHub(config)
    query_params = {k: v for k, v in params.items() if
                    v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'repo']}
    return github.make_request(params=query_params,
                               endpoint='repos/{0}/{1}/releases'.format(params.get('owner'), params.get('repo')))


def create_release(config, params):
    github = GitHub(config)
    payload = {k: v for k, v in params.items() if
               v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'repo']}
    return github.make_request(method='POST', data=json.dumps(payload),
                               endpoint='repos/{0}/{1}/releases'.format(params.get('owner'), params.get('repo')))


def list_stargazers(config, params):
    github = GitHub(config)
    query_params = {k: v for k, v in params.items() if
                    v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'repo']}
    return github.make_request(params=query_params,
                               endpoint='repos/{0}/{1}/stargazers'.format(params.get('owner'), params.get('repo')))


def star_repository(config, params):
    github = GitHub(config)
    return github.make_request(method='PUT',
                               endpoint='user/starred/{0}/{1}'.format(params.get('owner'), params.get('repo')))


def list_watchers(config, params):
    github = GitHub(config)
    query_params = {k: v for k, v in params.items() if
                    v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'repo']}
    return github.make_request(params=query_params,
                               endpoint='repos/{0}/{1}/subscribers'.format(params.get('owner'), params.get('repo')))


def set_repo_subscription(config, params):
    github = GitHub(config)
    payload = {k: v for k, v in params.items() if
               v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'repo']}
    return github.make_request(method='PUT', data=json.dumps(payload),
                               endpoint='repos/{0}/{1}/subscription'.format(params.get('owner'), params.get('repo')))


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
    'create_organization_repository': create_organization_repository,
    'fork_organization_repository': fork_organization_repository,
    'list_fork_repositories': list_fork_repositories,
    'list_organization_repositories': list_organization_repositories,
    'create_user_repository': create_user_repository,
    'create_repository_using_template': create_repository_using_template,
    'list_authenticated_user_repositories': list_authenticated_user_repositories,
    'list_user_repositories': list_user_repositories,
    'update_repository': update_repository,
    'add_repository_collaborator': add_repository_collaborator,
    'delete_repository': delete_repository,
    'get_branch_revision': get_branch_revision,
    'create_branch': create_branch,
    'merge_branch': merge_branch,
    'list_branches': list_branches,
    'fetch_upstream': fetch_upstream,
    'create_readme_file': create_readme_file,
    'clone_repository': clone_repository,
    'update_clone_repository': update_clone_repository,
    'push_repository': push_repository,
    'create_pull_request': create_pull_request,
    'list_pull_request': list_pull_request,
    'add_reviewers': add_reviewers,
    'merge_pull_request': merge_pull_request,
    'list_review_comments': list_review_comments,
    'list_releases': list_releases,
    'create_release': create_release,
    'list_stargazers': list_stargazers,
    'star_repository': star_repository,
    'list_watchers': list_watchers,
    'set_repo_subscription': set_repo_subscription
}
